"""Reset game progress or unlock a station in the local Docker Compose stack.

Run this on the PC/Pi hosting Docker. The host needs only Python and Docker;
database packages are used inside the existing backend image.
"""

import argparse
from pathlib import Path
import subprocess
import sys


# This script lives in gameClient; Compose and gameController are one level up.
ROOT = Path(__file__).resolve().parents[1]


def reset_database(station_id=None):
    """Commit the reset atomically; preserve registered teams and station settings."""
    from contextlib import closing

    import psycopg2
    from psycopg2.extras import RealDictCursor

    sys.path.insert(0, str(ROOT / "gameController"))
    from config import DB_CONFIG

    with closing(psycopg2.connect(**DB_CONFIG)) as conn:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL lock_timeout = '10s'")
            # The controller is stopped first. These locks also prevent concurrent
            # writes during the transaction if another process is still connected.
            cur.execute("LOCK TABLE station, station_state, results, station_events IN EXCLUSIVE MODE")
            if station_id is None:
                cur.execute("TRUNCATE results, station_events RESTART IDENTITY")
                cur.execute("DELETE FROM station_state")
                cur.execute("INSERT INTO station_state (station_id) SELECT station_id FROM station")
                message = "All game results/events cleared; every station is idle. Saved highscores and their round numbers are preserved."
            else:
                cur.execute("SELECT station_id FROM station WHERE station_id = %s", (station_id,))
                if cur.fetchone() is None:
                    raise ValueError(f"Unknown station: {station_id}")
                cur.execute("SELECT team_id, status FROM station_state WHERE station_id = %s",
                            (station_id,))
                state = cur.fetchone()
                if state is not None and state["team_id"] is not None:
                    # Release occupancy without changing any team's progress.
                    # Keep an audit entry for the manual unlock.
                    cur.execute(
                        """INSERT INTO station_events (station_id, team_id, event_type, "round")
                           VALUES (%s, %s, 'reset', COALESCE(
                               (SELECT MAX("round") FROM station_events WHERE team_id = %s), 1))""",
                        (station_id, state["team_id"], state["team_id"]),
                    )
                cur.execute(
                    """INSERT INTO station_state (station_id) VALUES (%s)
                       ON CONFLICT (station_id) DO UPDATE SET status = 'idle',
                           team_id = NULL,
                           updated_at = clock_timestamp()""",
                    (station_id,),
                )
                message = f"{station_id} unlocked. All results, event history, highscores, and other stations are preserved."
    print(f"[RESET] {message}", flush=True)


def compose(*args):
    """Always operate on this repository's Compose stack, regardless of cwd."""
    subprocess.run(["docker", "compose", "--project-directory", str(ROOT),
                    "-f", str(ROOT / "docker-compose.yml"), *args], cwd=ROOT, check=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--all", action="store_true", help="Delete ALL game results/events and set every station idle; keep teams/stations.")
    mode.add_argument("--station", metavar="ID", help="Unlock one station; preserve all results and highscores.")
    parser.add_argument("--database", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.station is not None and not args.station.strip():
        parser.error("--station requires a non-empty station ID")

    if args.database:
        try:
            reset_database(args.station)
        except Exception as exc:
            print(f"[RESET FAILED] Database transaction rolled back: {exc}", file=sys.stderr)
            return 1
        return 0

    selection = ["--station", args.station] if args.station else ["--all"]
    description = (f"Unlocking {args.station}" if args.station else
                   "Clearing ALL game results/events. Registered teams and stations will be kept.")
    print(f"[RESET] {description}", flush=True)
    stopped = False
    try:
        compose("up", "-d", "--wait", "postgres")
        compose("stop", "game-controller")
        stopped = True
        # The backend bind mount provides this script; no pip installation is
        # needed on the host. Bypass its normal migration entrypoint for recovery.
        compose("run", "--rm", "--no-deps", "--entrypoint", "python", "backend",
                "/app/gameClient/resetGame.py", "--database", *selection)
        compose("up", "-d", "mosquitto")
        compose("up", "-d", "--no-deps", "game-controller")
    except (OSError, subprocess.CalledProcessError, KeyboardInterrupt) as exc:
        print(f"[RESET FAILED] {exc}", file=sys.stderr)
        if stopped:
            print("Controller may still be stopped. After resolving the error, run: "
                  "docker compose up -d --no-deps game-controller", file=sys.stderr)
        return 1
    print("[DONE] Controller restarted, clearing pending handoffs and restarting its helper services. "
          "Query station status before resuming clients.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
