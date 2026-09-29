"""Generate timed game results, then leave three live station states for Grafana."""

import os
import random
import time

import clientLogin
import clientStatus


# Local script / local Docker: "localhost"; Docker on the Pi: "192.168.1.11"
MQTT_HOST = "localhost"
# MQTT_HOST = "192.168.1.11"
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "testen123")
RESPONSE_TIMEOUT = float(os.getenv("RESPONSE_TIMEOUT", "5"))

STATION_IDS = ("station_2", "station_3", "station_4", "station_5", "station_6")
STATION_COUNT = len(STATION_IDS)
START_STATION = "station_2"
# Each finished game gets a random duration for the Grafana timing panels.
PLAY_SECONDS_MIN = 2
PLAY_SECONDS_MAX = 10
STATION_WAIT_TIMEOUT = 30
POLL_SECONDS = 0.5

# Team ID, registered NFC UUID, and review score (0, 1, or 2).
TEAMS = (
    ("Team-01", "74 FA CB 01", 0),
    ("Team-02", "35 7F CB 01", 1),
    ("Team-03", "2C A1 19 49", 2),
)


def configure_clients():
    """Use this script's broker settings for both existing MQTT clients."""
    for module in (clientLogin, clientStatus):
        module.MQTT_HOST = MQTT_HOST
        module.MQTT_PORT = MQTT_PORT
        module.MQTT_PASSWORD = MQTT_PASSWORD
        module.RESPONSE_TIMEOUT = RESPONSE_TIMEOUT


def wait_for_idle(station_id):
    """Wait for a free station, including the release after a review handoff."""
    deadline = time.monotonic() + STATION_WAIT_TIMEOUT
    while True:
        status = clientStatus.request_status(station_id)
        if status is None:
            raise RuntimeError(f"No status reply from {station_id}.")
        if status.get("return") == "ERROR":
            raise RuntimeError(f"{station_id}: {status.get('message', 'Status query rejected.')}")
        if status["status"] == "idle" and status["team_id"] is None:
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError(f"{station_id} did not become idle within {STATION_WAIT_TIMEOUT:g} seconds.")
        time.sleep(min(POLL_SECONDS, remaining))


def send_action(station_id, team_id, nfc_uuid, action, review_score=None):
    """Stop on a rejected or missing reply rather than sending the next action."""
    response = clientLogin.send_request(station_id, nfc_uuid if action == "login" else team_id, action, review_score)
    if response is None:
        raise RuntimeError(f"{team_id} at {station_id}: no complete reply for {action}.")
    if response.get("return") == "ERROR":
        code = response.get("error_code", "ERROR")
        message = response.get("message", "Request rejected.")
        raise RuntimeError(f"{team_id} at {station_id}: {code}: {message}")
    if response.get("status") != clientLogin.ACTION_STATE[action] or response.get("team_id") != (None if action == "review" else team_id):
        raise RuntimeError(f"Unexpected reply for {team_id} at {station_id}: {response}")
    return response


def play_team(team_id, nfc_uuid, review_score):
    """Visit each station once, following the controller's nextStation replies."""
    stations = set(STATION_IDS)
    station_id = START_STATION
    visited = set()
    print(f"\n[TEAM] Starting a full round for {team_id} ({nfc_uuid}).", flush=True)

    while len(visited) < len(stations):
        if station_id not in stations or station_id in visited:
            raise RuntimeError(f"Invalid or repeated destination for {team_id}: {station_id!r}")
        print(f"[VISIT {len(visited) + 1}/{STATION_COUNT}] {team_id} at {station_id}", flush=True)
        wait_for_idle(station_id)
        send_action(station_id, team_id, nfc_uuid, "login")
        send_action(station_id, team_id, nfc_uuid, "start")
        simulate_play(station_id)
        send_action(station_id, team_id, nfc_uuid, "complete")
        review = send_action(station_id, team_id, nfc_uuid, "review", review_score)
        destination = review.get("next_station")

        # Receiving nextStation can precede the controller's database update to idle.
        wait_for_idle(station_id)
        visited.add(station_id)
        if review.get("routing_status") == "round_complete":
            if len(visited) != len(stations) or destination is not None:
                raise RuntimeError("Round finished unexpectedly; this simulation expects a fresh round.")
            break
        if destination not in stations or destination in visited:
            raise RuntimeError(f"Missing or invalid nextStation from {station_id}: {destination!r}")
        if review.get("routing_status") == "queued":
            print(f"[QUEUE] {team_id}: waiting for {destination} to become idle.", flush=True)
        station_id = destination

    # Round completion has no destination; a later login can start a new round.
    print(f"[TEAM DONE] {team_id}: completed all {STATION_COUNT} stations.", flush=True)


def simulate_play(station_id):
    """Keep the game running for a random duration before completing it."""
    seconds = random.randint(PLAY_SECONDS_MIN, PLAY_SECONDS_MAX)
    print(f"[PLAY] {station_id}: playing for {seconds} seconds.", flush=True)
    time.sleep(seconds)


def leave_live_states():
    """Start new visits with separate teams and stop at three different stages."""
    for station_id, (team_id, nfc_uuid, _), status in zip(
        STATION_IDS[:3], TEAMS, ("logged_in", "running", "reviewing")
    ):
        wait_for_idle(station_id)
        send_action(station_id, team_id, nfc_uuid, "login")
        if status in ("running", "reviewing"):
            send_action(station_id, team_id, nfc_uuid, "start")
        if status == "reviewing":
            simulate_play(station_id)
            send_action(station_id, team_id, nfc_uuid, "complete")
        # Do not submit review: its handoff would automatically release the station.
        print(f"[LIVE STATE] {station_id}: {status} with {team_id} (left occupied).", flush=True)


def main():
    configure_clients()
    try:
        if STATION_COUNT < 3 or len(TEAMS) != 3:
            raise ValueError("The demo requires at least three stations and exactly three teams.")
        if not 0 < PLAY_SECONDS_MIN <= PLAY_SECONDS_MAX:
            raise ValueError("Play durations must be positive with MIN <= MAX.")
        for team_id, nfc_uuid, review_score in TEAMS:
            play_team(team_id, nfc_uuid, review_score)
        # Reuse the first team's chip; the controller advances its round automatically.
        print(f"\n[EXTRA ROUND] Playing another full round with {TEAMS[0][0]}.", flush=True)
        play_team(*TEAMS[0])
        leave_live_states()
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"[STOPPED] {exc}", flush=True)
        print("Check station status before rerunning; accepted actions remain saved.", flush=True)
        return 1
    except KeyboardInterrupt:
        print("\n[STOPPED] Auto-play interrupted. Accepted actions remain saved.", flush=True)
        return 1
    print(f"\n[DONE] All {len(TEAMS)} teams completed a full round; {TEAMS[0][0]} completed an extra round.", flush=True)
    print("Three stations remain occupied for Grafana. Finish those visits before running auto-play again.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
