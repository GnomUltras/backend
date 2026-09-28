import json
import re

from psycopg2 import Error as DatabaseError, IntegrityError

import config
import db


# MQTT actions are transitions, not station states.
NEXT_ACTION = {"idle": "login", "logged_in": "start", "running": "complete", "reviewing": "review"}
# A saved review stays reviewing until the destination handoff releases it.
ACTION_STATE = {"login": "logged_in", "start": "running", "complete": "reviewing", "review": "reviewing"}
STATES = ("idle", "logged_in", "running", "reviewing")
GAME_ACTIONS = ("login", "start", "complete", "review")

# Only MQTT delivery bookkeeping is local. Game state always lives in PostgreSQL.
# MQTT message ID -> committed review snapshot awaiting acknowledgement.
pending_next_stations = {}


ERROR_MESSAGES = {
    "INVALID_PAYLOAD": "Send a UTF-8 JSON object. Login requires 'uuid'; other actions require 'team_id'.",
    "INVALID_TOPIC": "Use station/<station_id>/<action> with exactly three topic levels.",
    "INVALID_ACTION": "Supported game requests are login, start, complete, review, and status.",
    "INVALID_STATUS_REQUEST": "Status queries must be exactly {\"request\":\"GET\"}.",
    "RETAINED_REQUEST": "Game requests must be published with retain=false.",
    "INVALID_REVIEW_SCORE": "Review score must be 0, 1, or 2.",
    "UNKNOWN_TEAM": "The UUID is unmapped or the requested team is not configured in the database.",
    "STATION_BUSY": "The station is occupied. Wait until it is idle before logging in.",
    "INVALID_STATE": "This action is not allowed in the current state. Follow login, start, complete, review.",
    "TEAM_MISMATCH": "Only the team currently assigned to this station may advance its game.",
    "STATION_ALREADY_COMPLETED": "This team has already completed this station in this round.",
    "STATION_UNAVAILABLE": "The station is not configured or its database state is missing.",
    "HANDOFF_ERROR": "The review is saved, but destination delivery or station release failed. Query status; the handoff resumes on controller reconnect.",
    "DATABASE_ERROR": "The database operation failed. Query status and retry when available.",
}


class RequestRejectedError(ValueError):
    """A request that must be rejected without committing any game changes."""

    def __init__(self, error_code, message=None):
        self.error_code = error_code
        super().__init__(message or ERROR_MESSAGES[error_code])


class StationAlreadyCompletedError(RequestRejectedError):
    """The team's saved result prevents replaying this station in this round."""

    def __init__(self, message=None):
        super().__init__("STATION_ALREADY_COMPLETED", message)


def configured_station_ids():
    """Build the station names used in MQTT topics and database rows."""
    return [f"station{number:02d}" for number in range(1, config.STATION_COUNT + 1)]


def init_game():
    """Initialize stations without resetting progress or changing database-managed teams."""
    return db.init_db(configured_station_ids())


def change_station_state(station_id, team_id, action, review_score=None, expected_updated_at=None):
    """Validate a transition and save the result, station state, and event together."""
    if action not in (*GAME_ACTIONS, "idle"):
        raise RequestRejectedError("INVALID_ACTION")
    with db.station_transaction(station_id) as (cur, state):
        if state is None:
            raise RequestRejectedError("STATION_UNAVAILABLE")
        if action == "idle":
            # An old MQTT acknowledgement must never release a later visit.
            if (state["status"] != "reviewing" or state["review_score"] is None or state["team_id"] != team_id
                    or state["updated_at"] != expected_updated_at):
                return None
        elif NEXT_ACTION.get(state["status"]) != action:
            raise RequestRejectedError("STATION_BUSY" if action == "login" else "INVALID_STATE")
        elif action != "login" and state["team_id"] != team_id:
            raise RequestRejectedError("TEAM_MISMATCH")
        if action == "review" and state["review_score"] is not None:
            raise RequestRejectedError("INVALID_STATE", "The review is already saved; the next-station handoff is pending.")
        if action == "review" and (type(review_score) is not int or review_score not in (0, 1, 2)):
            raise RequestRejectedError("INVALID_REVIEW_SCORE")

        if not db.lock_team(cur, team_id):
            raise RequestRejectedError("UNKNOWN_TEAM")
        if action == "login":
            round_number = db.get_latest_round(cur, team_id)
            reviewed_stations = db.get_reviewed_stations(cur, team_id, round_number)
            # Reusing a chip starts a new round only after every station's review.
            if set(configured_station_ids()).issubset(reviewed_stations):
                round_number += 1
            previous_result = db.get_result(cur, team_id, station_id, round_number)
            if previous_result is not None and (
                previous_result["completed_at"] is not None
                or previous_result["status"] in ("complete", "review")
            ):
                raise StationAlreadyCompletedError(
                    f"{team_id} has already completed {station_id} in round {round_number}."
                )
        else:
            # A delayed handoff still belongs to the visit's original round.
            round_number = state["round"]
        # Use one database timestamp after acquiring the lock for every write.
        timestamp = db.get_timestamp(cur)
        if action == "login":
            # Only a new or unfinished result may be initialized by login.
            result = {"created_at": timestamp, "status": action,
                      "started_at": None, "completed_at": None, "review": None}
        elif action != "idle":
            result = db.get_result(cur, team_id, station_id, round_number)
            if result is None:
                raise IntegrityError("The occupied station has no matching result.")
            result["status"] = action
            # Play time runs from start to complete; review adds the team's score.
            if action == "start":
                result["started_at"] = timestamp
            elif action == "complete":
                result["completed_at"] = timestamp
            elif action == "review":
                result["review"] = str(review_score)
        if action != "idle":
            db.save_result(cur, team_id, station_id, round_number, result)

        score = review_score if action == "review" else None
        # Freeing a station clears its team assignment but keeps the team's result.
        new_state = db.save_station_state(
            cur, station_id, None if action == "idle" else team_id, "idle" if action == "idle" else ACTION_STATE[action], score, timestamp,
            None if action == "idle" else round_number,
        )
        db.log_event(cur, station_id, team_id, action, score, timestamp, round_number)
    # The transaction has committed before an MQTT handler can send a reply.
    print(f"[DB] {action}: {team_id} at {station_id}, round {round_number}", flush=True)
    return new_state


def on_connect(client, userdata, flags, reason_code, properties):
    """Subscribe to station messages and resume unfinished review handoffs."""
    if reason_code == 0:
        print("Game Controller running. Waiting for station updates...", flush=True)
        client.subscribe(config.MQTT_TOPIC, qos=1)
        # Re-send interrupted handoffs. Stations must tolerate duplicate replies.
        pending_next_stations.clear()
        try:
            for state in db.get_station_states("reviewing", configured_station_ids()):
                if state["review_score"] is not None:
                    send_next_station(client, state)
        except DatabaseError as exc:
            print(f"[DB ERROR] Could not resume review handoffs: {exc}", flush=True)
    else:
        print(f"Connection failed: {reason_code}", flush=True)


def publish_json(client, station_id, topic, payload):
    result = client.publish(f"station/{station_id}/{topic}", json.dumps(payload), qos=1, retain=False)
    label = "RETURN" if topic == "error" else topic.upper()
    print(f"[{label}] {station_id}: {json.dumps(payload)} (publish rc={result.rc})", flush=True)
    return result


def send_status(client, station_id, team_id, status):
    """Only actual station states are published on /status."""
    return publish_json(client, station_id, "status", {"status": status, "team_id": team_id}).rc == 0


def send_return(client, station_id, team_id, action, error_code=None, message=None):
    """Every handled request receives OK or ERROR on the /error response topic."""
    payload = {"return": "ERROR" if error_code else "OK", "action": action, "team_id": team_id}
    if error_code:
        payload.update(error_code=error_code, message=message or ERROR_MESSAGES[error_code])
    return publish_json(client, station_id, "error", payload).rc == 0


def send_error(client, station_id, team_id, action, error_code, message=None):
    return send_return(client, station_id, team_id, action, error_code, message)


def send_next_station(client, state):
    """Send the next destination and track its delivery before releasing the station."""
    station_id = state["station_id"]
    # Temporary routing rule: advance one station and wrap around at the end.
    stations = configured_station_ids()
    next_station = stations[(stations.index(station_id) + 1) % len(stations)]
    topic = f"station/{station_id}/nextStation"
    result = publish_json(client, station_id, "nextStation", {"next_station": next_station, "team_id": state["team_id"]})
    if result.rc != 0:
        print(f"[NEXT STATION ERROR] Could not send to {topic}: {result.rc}", flush=True)
        send_error(client, station_id, state["team_id"], "review", "HANDOFF_ERROR")
        return
    pending_next_stations[result.mid] = state
    print(f"[NEXT STATION] Queued {next_station} on {topic}; waiting for broker acknowledgement.", flush=True)


def on_publish(client, userdata, mid, reason_code, properties):
    """Return a reviewed station to idle after its destination reaches the broker."""
    state = pending_next_stations.pop(mid, None)
    if state is None:
        return
    station_id = state["station_id"]
    if reason_code.is_failure:
        print(f"[NEXT STATION ERROR] Broker rejected {station_id}: {reason_code}", flush=True)
        send_error(client, station_id, state["team_id"], "review", "HANDOFF_ERROR")
        return

    # This confirms broker receipt, not that the station processed the destination.
    # wait_for_publish() would block the same network loop needed to receive the ACK.
    try:
        new_state = change_station_state(
            station_id, state["team_id"], "idle", expected_updated_at=state["updated_at"]
        )
    except (DatabaseError, RequestRejectedError) as exc:
        print(f"[DB ERROR] Could not release {station_id}: {exc}", flush=True)
        send_error(client, station_id, state["team_id"], "review", "HANDOFF_ERROR")
        return
    if new_state is not None:
        send_status(client, station_id, None, "idle")
        send_return(client, station_id, state["team_id"], "review")
        print(f"[IDLE] {station_id}: next-station message acknowledged; ready for a new team.", flush=True)


def on_message(client, userdata, msg):
    """Validate a station request, apply its game action, and send the response."""
    parts = msg.topic.split("/")
    # A malformed topic still gets an error if it contains a safe reply address.
    if len(parts) < 2 or parts[0] != "station" or not re.fullmatch(r"[A-Za-z0-9_-]{1,50}", parts[1]):
        print(f"[INVALID_TOPIC] Cannot route a reply for {msg.topic!r}.", flush=True)
        return
    station_id = parts[1]
    action = parts[2] if len(parts) > 2 and parts[2] else None
    if len(parts) != 3 or action is None:
        send_error(client, station_id, None, action, "INVALID_TOPIC")
        return
    # These are independent services or controller output, not game requests.
    if action in ("servertime", "test", "nextStation", "error"):
        return
    if action not in (*GAME_ACTIONS, "status"):
        send_error(client, station_id, None, action, "INVALID_ACTION")
        return

    try:
        request = json.loads(msg.payload.decode("utf-8"))
        if not isinstance(request, dict):
            raise ValueError("Request must be a JSON object.")
    except (ValueError, UnicodeDecodeError, RecursionError):
        send_error(client, station_id, None, action, "INVALID_PAYLOAD")
        return

    # Status replies share the request topic. Ignore them to avoid response loops.
    if (action == "status" and "request" not in request and "team_id" in request
            and request.get("status") in STATES):
        return
    if msg.retain:
        send_error(client, station_id, None, action, "RETAINED_REQUEST")
        return
    if station_id not in configured_station_ids():
        send_error(client, station_id, None, action, "STATION_UNAVAILABLE")
        return
    if action == "status" and request != {"request": "GET"}:
        send_error(client, station_id, None, action, "INVALID_STATUS_REQUEST")
        return
    if action == "status":
        print(f"[STATUS REQUEST] Received from {station_id} on {msg.topic}", flush=True)
        try:
            current_state = db.get_station_state(station_id)
        except DatabaseError as exc:
            print(f"[DB ERROR] Could not read {station_id}: {exc}", flush=True)
            send_error(client, station_id, None, action, "DATABASE_ERROR")
            return
        if current_state is None:
            send_error(client, station_id, None, action, "STATION_UNAVAILABLE")
            return
        # Status queries are read-only and independent of the allowed next action.
        send_status(client, station_id, current_state["team_id"], current_state["status"])
        send_return(client, station_id, current_state["team_id"], action)
        return

    identifier = request.get("uuid" if action == "login" else "team_id")
    if not isinstance(identifier, str) or not identifier.strip():
        send_error(client, station_id, None, action, "INVALID_PAYLOAD")
        return
    # Only login scans the chip. Later actions use the resolved team from /status.
    try:
        team_id = db.get_team_name(identifier.strip()) if action == "login" else identifier.strip()
    except DatabaseError as exc:
        print(f"[DB ERROR] Could not resolve login at {station_id}: {exc}", flush=True)
        send_error(client, station_id, None, action, "DATABASE_ERROR")
        return
    if not isinstance(team_id, str) or not team_id.strip() or len(team_id) > 255:
        send_error(client, station_id, None, action, "UNKNOWN_TEAM")
        return
    review_score = request.get("score") if action == "review" else None
    if action == "review" and (type(review_score) is not int or review_score not in (0, 1, 2)):
        send_error(client, station_id, team_id, action, "INVALID_REVIEW_SCORE")
        return

    try:
        new_state = change_station_state(station_id, team_id, action, review_score)
    except RequestRejectedError as exc:
        # The transaction rolled back, so the group can correct the request and retry.
        print(f"[{action.upper()} REJECTED] {exc.error_code}: {exc}", flush=True)
        send_error(client, station_id, team_id, action, exc.error_code, str(exc))
        return
    except DatabaseError as exc:
        print(f"[DB ERROR] Could not save {action} for {station_id}: {exc}", flush=True)
        send_error(client, station_id, team_id, action, "DATABASE_ERROR")
        return
    if new_state is None:
        return

    # Review success is confirmed after the handoff and committed reset to idle.
    if action == "review":
        send_next_station(client, new_state)
    else:
        send_status(client, station_id, new_state["team_id"], new_state["status"])
        send_return(client, station_id, team_id, action)
    print(f"[{action.upper()}] {team_id} at {station_id}.", flush=True)
