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
            return None
        if action == "idle":
            # An old MQTT acknowledgement must never release a later visit.
            if (state["status"] != "review" or state["team_id"] != team_id
                    or state["updated_at"] != expected_updated_at):
                return None
        elif NEXT_ACTION.get(state["status"]) != action:
            return None
        elif action != "login" and state["team_id"] != team_id:
            return None
        if action == "review" and review_score not in (0, 1, 2):
            return None

        if not db.team_exists(cur, team_id):
            return None
        # Use one database timestamp after acquiring the lock for every write.
        timestamp = db.get_timestamp(cur)
        if action == "login":
            # Keep the latest result per team/station; earlier visits stay in events.
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


def send_status(client, station_id, team_id, status):
    payload = {"status": status, "team_id": team_id}
    result = client.publish(f"station/{station_id}/status", json.dumps(payload), qos=1, retain=False)
    if result.rc == 0:
        print(f"[STATUS RESPONSE] Sent to {station_id}: {json.dumps(payload)}", flush=True)
    else:
        print(f"[STATUS ERROR] Could not send response to {station_id}: {result.rc}", flush=True)
    return result.rc == 0


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
        return

    # JSON status replies on the shared topic must not query the DB or loop.
    if action == "status" and msg.payload.strip() != b"1":
        return
    if action == "status":
        print(f"[STATUS REQUEST] Received from {station_id} on {msg.topic}", flush=True)
    try:
        current_state = db.get_station_state(station_id)
        if current_state is None:
            raise DatabaseError(f"Station {station_id} is not initialized.")
    except DatabaseError as exc:
        print(f"[DB ERROR] Could not read {station_id}: {exc}", flush=True)
        send_status(client, station_id, None, "error")
        return
    # Status queries are read-only and independent of the allowed next action.
    if action == "status":
        send_status(client, station_id, current_state["team_id"], current_state["status"])
        return

    # Ignore duplicates and out-of-order requests before processing their payload.
    if action != NEXT_ACTION.get(current_state["status"]):
        return

    try:
        nfc_uuid = msg.payload.decode("utf-8").strip()
        review_score = None
        # Review payload: <nfc_uuid>;<score>. Other actions carry only the UUID.
        if action == "review":
            nfc_uuid, score = nfc_uuid.rsplit(";", 1)
            nfc_uuid = nfc_uuid.strip()
            if score.strip() not in ("0", "1", "2"):
                raise ValueError("Review score must be 0, 1, or 2.")
            review_score = int(score)
    except (ValueError, UnicodeDecodeError):
        send_status(client, station_id, None, "error")
        return

    team_id = config.NFC_TEAMS.get(nfc_uuid)
    # Only the logged-in team can advance the station until review succeeds.
    if action != "login" and team_id != current_state["team_id"]:
        return

    if not isinstance(team_id, str) or not team_id.strip() or len(team_id) > 50:
        print("[ERROR] NFC UUID has no valid team mapping.", flush=True)
        send_status(client, station_id, None, "error")
        return

    try:
        new_state = change_station_state(station_id, team_id, action, review_score)
    except DatabaseError as exc:
        print(f"[DB ERROR] Could not save {action} for {station_id}: {exc}", flush=True)
        send_status(client, station_id, team_id, "error")
        return
    if new_state is None:
        return

    # Confirm only after the review checks, DB commit, and state update succeed.
    status_sent = send_status(client, station_id, team_id, action)
    print(f"[{action.upper()}] {team_id} at {station_id}.", flush=True)
    if action == "review" and status_sent:
        send_next_station(client, new_state)
