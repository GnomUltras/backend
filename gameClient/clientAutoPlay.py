"""Play four teams concurrently: finish two and leave two partway through a game."""

from concurrent.futures import ThreadPoolExecutor, as_completed
import os
import random
import time
from threading import Event, Lock

import clientLogin
import clientStatus


# Local script / local Docker: "localhost"; Docker on the Pi: "192.168.1.11"
# MQTT_HOST = "localhost"
MQTT_HOST = "192.168.1.11"
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
    ("Team-04", "63 12 46 16", 1),
)

# Serialize simulated visitors to each station, not the entire game. This also
# keeps MQTT replies unambiguous because the protocol has no request IDs.
STATION_LOCKS = {station_id: Lock() for station_id in STATION_IDS}
STOP = Event()
FULL_GAMES_DONE = (Event(), Event())
# The other teams finish two visits, then stop at their third station.
PARTIAL_VISITS = 2


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
        if STOP.is_set():
            raise RuntimeError("Auto-play stopped.")
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
        STOP.wait(min(POLL_SECONDS, remaining))


def send_action(station_id, team_id, nfc_uuid, action, review_score=None):
    """Stop on a rejected or missing reply rather than sending the next action."""
    if STOP.is_set():
        raise RuntimeError("Auto-play stopped.")
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


def play_team(team_id, nfc_uuid, review_score, start_station=None, stop_state=None):
    """Follow routing through a full game or stop partway through the demo."""
    stations = set(STATION_IDS)
    station_id = start_station or START_STATION
    visited = set()
    print(f"\n[TEAM] Starting a game for {team_id} ({nfc_uuid}).", flush=True)

    while len(visited) < len(stations):
        if stop_state is not None and len(visited) == PARTIAL_VISITS:
            leave_partial_visit(team_id, nfc_uuid, station_id, visited, stop_state)
            return
        if station_id not in stations or station_id in visited:
            raise RuntimeError(f"Invalid or repeated destination for {team_id}: {station_id!r}")
        print(f"[VISIT {len(visited) + 1}/{STATION_COUNT}] {team_id} at {station_id}", flush=True)
        # Hold only this station's lock, releasing it before moving elsewhere.
        # Other teams continue playing at their own stations in parallel.
        with STATION_LOCKS[station_id]:
            wait_for_idle(station_id)
            send_action(station_id, team_id, nfc_uuid, "login")
            send_action(station_id, team_id, nfc_uuid, "start")
            simulate_play(station_id)
            send_action(station_id, team_id, nfc_uuid, "complete")
            review = send_action(station_id, team_id, nfc_uuid, "review", review_score)
        destination = review.get("next_station")

        # The action client already waited for idle, review OK, and the route.
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
    seconds = random.uniform(PLAY_SECONDS_MIN, PLAY_SECONDS_MAX)
    print(f"[PLAY] {station_id}: playing for {seconds:.2f} seconds.", flush=True)
    if STOP.wait(seconds):
        raise RuntimeError("Auto-play stopped.")


def leave_partial_visit(team_id, nfc_uuid, destination, visited, stop_state):
    """Leave a third visit open after both full-game teams have finished."""
    # Wait between visits, with no station occupied or lock held. Otherwise a
    # parked team could permanently block a station either finishing team needs.
    print(f"[DEMO WAIT] {team_id}: {len(visited)} stations done; waiting to leave a live state.", flush=True)
    for completed in FULL_GAMES_DONE:
        while not completed.wait(0.1):
            if STOP.is_set():
                raise RuntimeError("Auto-play stopped.")
    index = STATION_IDS.index(destination)
    candidates = STATION_IDS[index:] + STATION_IDS[:index]
    for station_id in candidates:
        if station_id in visited:
            continue
        with STATION_LOCKS[station_id]:
            if STOP.is_set():
                raise RuntimeError("Auto-play stopped.")
            status = clientStatus.request_status(station_id)
            if status is None or status.get("return") == "ERROR":
                raise RuntimeError(f"Could not read demo station {station_id}: {status}")
            if status["status"] != "idle" or status["team_id"] is not None:
                continue  # The other parked team may have taken the suggested station.
            send_action(station_id, team_id, nfc_uuid, "login")
            send_action(station_id, team_id, nfc_uuid, "start")
            if stop_state == "reviewing":
                simulate_play(station_id)
                send_action(station_id, team_id, nfc_uuid, "complete")
            print(f"[LIVE STATE] {team_id} at {station_id}: {stop_state}; game unfinished.", flush=True)
            return
    raise RuntimeError(f"No free, unvisited demo station for {team_id}.")


def run_team(team, start_station, stop_state, completed=None):
    play_team(*team, start_station, stop_state)
    if completed is not None:
        completed.set()


def main():
    configure_clients()
    STOP.clear()
    for completed in FULL_GAMES_DONE:
        completed.clear()
    try:
        if STATION_COUNT < PARTIAL_VISITS + 2 or len(TEAMS) != 4:
            raise ValueError("The demo requires at least four stations and exactly four teams.")
        if not 0 <= PLAY_SECONDS_MIN <= PLAY_SECONDS_MAX:
            raise ValueError("Play durations must be non-negative with MIN <= MAX.")
        first = STATION_IDS.index(START_STATION)
        with ThreadPoolExecutor(max_workers=len(TEAMS)) as pool:
            jobs = [pool.submit(run_team, team, STATION_IDS[(first + i) % STATION_COUNT], stop_state,
                                FULL_GAMES_DONE[i] if i < 2 else None)
                    for i, (team, stop_state) in enumerate(zip(TEAMS, (None, None, "running", "reviewing")))]
            try:
                for job in as_completed(jobs):
                    job.result()
            except BaseException:
                # Wake sleeping/waiting teams before the executor joins them.
                STOP.set()
                raise
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"[STOPPED] {exc}", flush=True)
        print("Check station status before rerunning; accepted actions remain saved.", flush=True)
        return 1
    except KeyboardInterrupt:
        print("\n[STOPPED] Auto-play interrupted. Accepted actions remain saved.", flush=True)
        return 1
    print(f"\n[DONE] {TEAMS[0][0]} and {TEAMS[1][0]} completed one round each. "
          f"{TEAMS[2][0]} remains running; {TEAMS[3][0]} remains reviewing "
          "after two finished stations each.", flush=True)
    print("Finish or unlock the two occupied stations before rerunning auto-play.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
