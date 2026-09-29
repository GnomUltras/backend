from contextlib import closing, contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor

import config


STATE_COLUMNS = 'station_id, team_id, status, review_score, updated_at, "round"'


def init_db(station_ids):
    """Add missing stations and state rows after migrations, preserving progress."""
    try:
        with closing(psycopg2.connect(**config.DB_CONFIG)) as conn:
            with conn, conn.cursor() as cur:
                cur.execute('SELECT started_at, completed_at, "round" FROM results LIMIT 0')
                cur.execute('SELECT "round" FROM station_state LIMIT 0')
                cur.execute('SELECT "round" FROM station_events LIMIT 0')
                cur.execute('SELECT id, name FROM team LIMIT 0')
                for station_id in station_ids:
                    cur.execute(
                        "INSERT INTO station (station_id, name) VALUES (%s, %s) "
                        "ON CONFLICT (station_id) DO UPDATE SET name = EXCLUDED.name",
                        (station_id, station_id),
                    )
                    cur.execute(
                        "INSERT INTO station_state (station_id) VALUES (%s) "
                        "ON CONFLICT (station_id) DO NOTHING",
                        (station_id,),
                    )
        print("[DB] PostgreSQL ready. Existing station states preserved.", flush=True)
        return True
    except psycopg2.Error as exc:
        print(f"[DB ERROR] Initialization failed. Apply Alembic migrations first: {exc}", flush=True)
        return False


def get_team_name(chip_id):
    """Resolve team.id (scanned chip) to team.name, used by all game records."""
    with closing(psycopg2.connect(**config.DB_CONFIG)) as conn:
        with conn, conn.cursor() as cur:
            cur.execute("SELECT name FROM team WHERE id = %s", (chip_id,))
            row = cur.fetchone()
            return row[0] if row else None


def get_station_state(station_id):
    """Read the current committed state; no local state cache is used."""
    with closing(psycopg2.connect(**config.DB_CONFIG)) as conn:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(f"SELECT {STATE_COLUMNS} FROM station_state WHERE station_id = %s", (station_id,))
            return cur.fetchone()


def get_station_states(status, station_ids):
    """Find stations in a given state, such as reviews awaiting a handoff on reconnect."""
    with closing(psycopg2.connect(**config.DB_CONFIG)) as conn:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"SELECT {STATE_COLUMNS} FROM station_state "
                "WHERE status = %s AND station_id = ANY(%s) ORDER BY station_id",
                (status, station_ids),
            )
            return cur.fetchall()


def get_routing_snapshot(team_id, round_number, station_ids):
    """Read station occupancy and this team's results from one database snapshot."""
    with closing(psycopg2.connect(**config.DB_CONFIG)) as conn:
        conn.set_session(isolation_level="REPEATABLE READ", readonly=True)
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT name FROM team WHERE name = %s", (team_id,))
            if cur.fetchone() is None:
                return None
            cur.execute(
                """SELECT s.station_id, ss.status, ss.team_id,
                          r.status AS result_status, r.completed_at
                   FROM station AS s
                   LEFT JOIN station_state AS ss ON ss.station_id = s.station_id
                   LEFT JOIN results AS r ON r.station_id = s.station_id
                       AND r.team_id = %s AND r."round" = %s
                   WHERE s.station_id = ANY(%s)""",
                (team_id, round_number, station_ids),
            )
            return cur.fetchall()


@contextmanager
def station_transaction(station_id):
    """Hold the row lock while gameLogic checks and writes a transition.

    Commit only after the caller leaves this block successfully. Any exception
    rolls back all writes; concurrent station requests wait for the row lock.
    """
    with closing(psycopg2.connect(**config.DB_CONFIG)) as conn:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"SELECT {STATE_COLUMNS} FROM station_state WHERE station_id = %s FOR UPDATE",
                (station_id,),
            )
            yield cur, cur.fetchone()


def lock_team(cur, team_id):
    """Serialize a team's transitions across stations, including round changes."""
    cur.execute("SELECT 1 FROM team WHERE name = %s FOR UPDATE", (team_id,))
    return cur.fetchone() is not None


def get_latest_round(cur, team_id):
    """Read the latest saved round, starting at 1 for a team with no results."""
    cur.execute('SELECT COALESCE(MAX("round"), 1) AS "round" FROM results WHERE team_id = %s', (team_id,))
    return cur.fetchone()["round"]


def get_reviewed_stations(cur, team_id, round_number):
    """Return the stations whose games and reviews are finished in this round."""
    cur.execute(
        'SELECT station_id FROM results WHERE team_id = %s AND "round" = %s '
        "AND status = 'review' AND completed_at IS NOT NULL",
        (team_id, round_number),
    )
    return {row["station_id"] for row in cur.fetchall()}


def get_timestamp(cur):
    """Use the database clock for game timestamps."""
    cur.execute("SELECT clock_timestamp() AS now")
    return cur.fetchone()["now"]


def get_result(cur, team_id, station_id, round_number):
    """Read a team's progress at one station in the specified round."""
    cur.execute(
        "SELECT created_at, status, started_at, completed_at, review FROM results "
        'WHERE team_id = %s AND station_id = %s AND "round" = %s',
        (team_id, station_id, round_number),
    )
    return cur.fetchone()


def save_result(cur, team_id, station_id, round_number, result):
    """Save this round's result without overwriting a previous group's visit."""
    cur.execute(
        """INSERT INTO results
               (team_id, station_id, "round", created_at, status, started_at, completed_at, review)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (team_id, "round", station_id) DO UPDATE SET
               created_at = EXCLUDED.created_at, status = EXCLUDED.status,
               started_at = EXCLUDED.started_at, completed_at = EXCLUDED.completed_at,
               review = EXCLUDED.review""",
        (team_id, station_id, round_number, result["created_at"], result["status"],
         result["started_at"], result["completed_at"], result["review"]),
    )


def save_station_state(cur, station_id, team_id, status, review_score, timestamp, round_number):
    """Update the station's current occupancy and return its new state."""
    cur.execute(
        f"""UPDATE station_state SET team_id = %s, status = %s,
               review_score = %s, updated_at = %s, "round" = %s
               WHERE station_id = %s RETURNING {STATE_COLUMNS}""",
        (team_id, status, review_score, timestamp, round_number, station_id),
    )
    return cur.fetchone()


def log_event(cur, station_id, team_id, event_type, review_score, timestamp, round_number):
    """Append a transition with its team and round for the dashboard."""
    cur.execute(
        """INSERT INTO station_events (created_at, station_id, team_id, event_type, review_score, "round")
           VALUES (%s, %s, %s, %s, %s, %s)""",
        (timestamp, station_id, team_id, event_type, review_score, round_number),
    )
