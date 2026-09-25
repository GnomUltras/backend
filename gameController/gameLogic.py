import json

from psycopg2 import Error as DatabaseError, IntegrityError

import config
import db


NEXT_ACTION = {
    "idle": "login",
    "login": "start",
    "start": "complete",
    "complete": "review",
}

# Only MQTT delivery bookkeeping is local. Game state always lives in PostgreSQL.
# MQTT message ID -> committed review snapshot awaiting acknowledgement.
pending_next_stations = {}


ERROR_MESSAGES = {
    "INVALID_PAYLOAD": "Send a UTF-8 JSON object with a non-empty string field 'nfc_uuid'.",
    "INVALID_REVIEW_SCORE": "Review score must be 0, 1, or 2.",
    "UNKNOWN_TEAM": "The NFC UUID does not identify a configured team in the database.",
    "STATION_BUSY": "The station is occupied. Wait until it is idle before logging in.",
    "INVALID_STATE": "Review is only allowed after the game has completed.",
    "TEAM_MISMATCH": "Only the team currently assigned to this station may submit its review.",
    "STATION_ALREADY_COMPLETED": "This team has already completed this station in this run.",
    "STATION_UNAVAILABLE": "The station is not configured or its database state is missing.",
    "DATABASE_ERROR": "The database operation failed. Query status and retry when available.",
}


class RequestRejectedError(ValueError):
    """A request that must be rejected without committing any game changes."""

    def __init__(self, error_code, message=None):
        self.error_code = error_code
        super().__init__(message or ERROR_MESSAGES[error_code])


class StationAlreadyCompletedError(RequestRejectedError):
    """The team's saved result prevents replaying this station in this run."""

    def __init__(self, message=None):
        super().__init__("STATION_ALREADY_COMPLETED", message)


def configured_station_ids():
    return [f"station{number:02d}" for number in range(1, config.STATION_COUNT + 1)]


def init_game():
    """Validate game configuration and supply the database's initial catalog."""
    names = list(config.NFC_TEAMS.values())
    if any(not isinstance(name, str) or not name.strip() or len(name) > 50 for name in names):
        print("[ERROR] Configured team names must contain 1 to 50 characters.", flush=True)
        return False
    return db.init_db(sorted(set(names)), configured_station_ids())


def change_station_state(station_id, team_id, action, review_score=None, expected_updated_at=None):
    """Check the locked current state and decide all changes before committing."""
    with db.station_transaction(station_id) as (cur, state):
        if state is None:
            if action in ("login", "review"):
                raise RequestRejectedError("STATION_UNAVAILABLE")
            return None
        if action == "idle":
            # An old MQTT acknowledgement must never release a later visit.
            if (state["status"] != "review" or state["team_id"] != team_id
                    or state["updated_at"] != expected_updated_at):
                return None
        elif NEXT_ACTION.get(state["status"]) != action:
            if action in ("login", "review"):
                raise RequestRejectedError("STATION_BUSY" if action == "login" else "INVALID_STATE")
            return None
        elif action != "login" and state["team_id"] != team_id:
            if action == "review":
                raise RequestRejectedError("TEAM_MISMATCH")
            return None
        if action == "review" and (type(review_score) is not int or review_score not in (0, 1, 2)):
            raise RequestRejectedError("INVALID_REVIEW_SCORE")

        if not db.team_exists(cur, team_id):
            if action in ("login", "review"):
                raise RequestRejectedError("UNKNOWN_TEAM")
            return None
        if action == "login":
            previous_result = db.get_result(cur, team_id, station_id)
            if previous_result is not None and (
                previous_result["completed_at"] is not None
                or previous_result["status"] in ("complete", "review")
            ):
                raise StationAlreadyCompletedError(
                    f"{team_id} has already completed {station_id} in this run."
                )
        # Use one database timestamp after acquiring the lock for every write.
        timestamp = db.get_timestamp(cur)
        if action == "login":
            # Only a new or unfinished result may be initialized by login.
            result = {"created_at": timestamp, "status": action,
                      "started_at": None, "completed_at": None, "review": None}
        elif action != "idle":
            result = db.get_result(cur, team_id, station_id)
            if result is None:
                raise IntegrityError("The occupied station has no matching result.")
            result["status"] = action
            if action == "start":
                result["started_at"] = timestamp
            elif action == "complete":
                result["completed_at"] = timestamp
            elif action == "review":
                result["review"] = str(review_score)
        if action != "idle":
            db.save_result(cur, team_id, station_id, result)

        score = review_score if action == "review" else None
        new_state = db.save_station_state(
            cur, station_id, None if action == "idle" else team_id, action, score, timestamp
        )
        db.log_event(cur, station_id, team_id, action, score, timestamp)
    # The transaction has committed before an MQTT handler can send a reply.
    print(f"[DB] {action}: {team_id} at {station_id}", flush=True)
    return new_state


def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        print("Game Controller running. Waiting for station updates...", flush=True)
        client.subscribe(config.MQTT_TOPIC, qos=1)
        # Re-send interrupted handoffs. Stations must tolerate duplicate replies.
        pending_next_stations.clear()
        try:
            for state in db.get_station_states("review", configured_station_ids()):
                if send_status(client, state["station_id"], state["team_id"], "review"):
                    send_next_station(client, state)
        except DatabaseError as exc:
            print(f"[DB ERROR] Could not resume review handoffs: {exc}", flush=True)
    else:
        print(f"Connection failed: {reason_code}", flush=True)


def send_status(client, station_id, team_id, status, *, action=None, error_code=None):
    payload = {"status": status, "team_id": team_id}
    if error_code is not None:
        payload.update(action=action, error_code=error_code, message=ERROR_MESSAGES[error_code])
    result = client.publish(f"station/{station_id}/status", json.dumps(payload), qos=1, retain=False)
    if result.rc == 0:
        print(f"[STATUS RESPONSE] Sent to {station_id}: {json.dumps(payload)}", flush=True)
    else:
        print(f"[STATUS ERROR] Could not send response to {station_id}: {result.rc}", flush=True)
    return result.rc == 0


def send_error(client, station_id, team_id, action, error_code):
    # Preserve the existing response format for actions outside login/review.
    if action in ("login", "review"):
        return send_status(client, station_id, team_id, "error", action=action, error_code=error_code)
    return send_status(client, station_id, team_id, "error")


def send_next_station(client, state):
    station_id = state["station_id"]
    # Temporary routing rule: advance one station and wrap around at the end.
    stations = configured_station_ids()
    next_station = stations[(stations.index(station_id) + 1) % len(stations)]
    topic = f"station/{station_id}/nextStation"
    result = client.publish(topic, next_station, qos=1, retain=False)
    if result.rc != 0:
        print(f"[NEXT STATION ERROR] Could not send to {topic}: {result.rc}", flush=True)
        return
    pending_next_stations[result.mid] = state
    print(f"[NEXT STATION] Queued {next_station} on {topic}; waiting for broker acknowledgement.", flush=True)


def on_publish(client, userdata, mid, reason_code, properties):
    state = pending_next_stations.pop(mid, None)
    if state is None:
        return
    station_id = state["station_id"]
    if reason_code.is_failure:
        print(f"[NEXT STATION ERROR] Broker rejected {station_id}: {reason_code}", flush=True)
        return

    # QoS 1 is acknowledged by the broker here. Never block the MQTT callback
    # with wait_for_publish(), which needs this same network loop to continue.
    try:
        new_state = change_station_state(
            station_id, state["team_id"], "idle", expected_updated_at=state["updated_at"]
        )
    except DatabaseError as exc:
        print(f"[DB ERROR] Could not release {station_id}: {exc}", flush=True)
        return
    if new_state is not None:
        print(f"[IDLE] {station_id}: next-station message acknowledged; ready for a new team.", flush=True)


def on_message(client, userdata, msg):
    parts = msg.topic.split("/")
    if len(parts) != 3 or parts[0] != "station" or msg.retain:
        return

    station_id, action = parts[1], parts[2]
    if action not in ("login", "start", "complete", "review", "status"):
        return

    if station_id not in configured_station_ids():
        if action in ("login", "review"):
            send_error(client, station_id, None, action, "STATION_UNAVAILABLE")
        return

    try:
        request = json.loads(msg.payload.decode("utf-8"))
        if not isinstance(request, dict):
            raise ValueError("Request must be a JSON object.")
    except (ValueError, UnicodeDecodeError):
        # Status queries and replies share a topic: never answer malformed echoes.
        if action != "status":
            send_error(client, station_id, None, action, "INVALID_PAYLOAD")
        return

    # Only a GET request may query the DB; our own status/error replies must not loop.
    if action == "status" and request != {"request": "GET"}:
        return
    if action == "status":
        print(f"[STATUS REQUEST] Received from {station_id} on {msg.topic}", flush=True)
    try:
        current_state = db.get_station_state(station_id)
        if current_state is None:
            send_error(client, station_id, None, action, "STATION_UNAVAILABLE")
            return
    except DatabaseError as exc:
        print(f"[DB ERROR] Could not read {station_id}: {exc}", flush=True)
        send_error(client, station_id, None, action, "DATABASE_ERROR")
        return
    # Status queries are read-only and independent of the allowed next action.
    if action == "status":
        send_status(client, station_id, current_state["team_id"], current_state["status"])
        return

    # Login/review are checked again under the transaction lock, with error codes.
    # Keep the existing silent handling for out-of-order start/complete requests.
    if action not in ("login", "review") and action != NEXT_ACTION.get(current_state["status"]):
        return

    nfc_uuid = request.get("nfc_uuid")
    if not isinstance(nfc_uuid, str) or not nfc_uuid.strip():
        send_error(client, station_id, None, action, "INVALID_PAYLOAD")
        return
    nfc_uuid = nfc_uuid.strip()

    team_id = config.NFC_TEAMS.get(nfc_uuid)
    review_score = None
    if action == "review":
        review_score = request.get("review_score")
        if type(review_score) is not int or review_score not in (0, 1, 2):
            # Do not expose an invalid configured team value in a JSON reply.
            known_team = team_id if isinstance(team_id, str) and team_id.strip() and len(team_id) <= 50 else None
            send_error(client, station_id, known_team, action, "INVALID_REVIEW_SCORE")
            return
    # Only the logged-in team can advance the station until review succeeds.
    if action in ("start", "complete") and team_id != current_state["team_id"]:
        return

    if not isinstance(team_id, str) or not team_id.strip() or len(team_id) > 50:
        print("[ERROR] NFC UUID has no valid team mapping.", flush=True)
        send_error(client, station_id, None, action, "UNKNOWN_TEAM")
        return

    try:
        new_state = change_station_state(station_id, team_id, action, review_score)
    except RequestRejectedError as exc:
        print(f"[{action.upper()} REJECTED] {exc.error_code}: {exc}", flush=True)
        send_error(client, station_id, team_id, action, exc.error_code)
        return
    except DatabaseError as exc:
        print(f"[DB ERROR] Could not save {action} for {station_id}: {exc}", flush=True)
        send_error(client, station_id, team_id, action, "DATABASE_ERROR")
        return
    if new_state is None:
        return

    # Confirm only after the review checks, DB commit, and state update succeed.
    status_sent = send_status(client, station_id, team_id, action)
    print(f"[{action.upper()}] {team_id} at {station_id}.", flush=True)
    if action == "review" and status_sent:
        send_next_station(client, new_state)
