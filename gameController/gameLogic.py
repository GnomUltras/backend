import json

import config
from db import log_event_to_db


station_states = {
    station_id: {"team_id": None, "status": "idle"}
    for station_id in range(1, config.STATION_COUNT + 1)
}

# MQTT message ID -> station awaiting acknowledgement of its destination.
pending_next_stations = {}

NEXT_ACTION = {
    "idle": "login",
    "login": "start",
    "start": "complete",
    "complete": "review",
}


def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        print("Game Controller running. Waiting for station updates...", flush=True)
        client.subscribe(config.MQTT_TOPIC, qos=1)
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


def send_next_station(client, station_id):
    # Temporary routing rule: advance one station and wrap around at the end.
    next_station = f"station{station_id % config.STATION_COUNT + 1:02d}"
    topic = f"station/station{station_id:02d}/nextStation"
    result = client.publish(topic, next_station, qos=1, retain=False)
    if result.rc != 0:
        print(f"[NEXT STATION ERROR] Could not send to {topic}: {result.rc}", flush=True)
        return
    pending_next_stations[result.mid] = station_id
    print(f"[NEXT STATION] Queued {next_station} on {topic}; waiting for broker acknowledgement.", flush=True)


def on_publish(client, userdata, mid, reason_code, properties):
    station_id = pending_next_stations.pop(mid, None)
    if station_id is None:
        return
    if reason_code.is_failure:
        print(f"[NEXT STATION ERROR] Broker rejected station {station_id}: {reason_code}", flush=True)
        return

    current_state = station_states[station_id]
    if current_state["status"] != "review":
        return
    # QoS 1 is acknowledged by the broker here. Never block the MQTT callback
    # with wait_for_publish(), which needs this same network loop to continue.
    if not log_event_to_db(station_id, current_state["team_id"], "idle"):
        return
    station_states[station_id] = {"team_id": None, "status": "idle"}
    print(f"[IDLE] Station {station_id}: next-station message acknowledged; ready for a new team.", flush=True)


def on_message(client, userdata, msg):
    parts = msg.topic.split("/")
    if len(parts) != 3 or parts[0] != "station" or msg.retain:
        return

    raw_station_id, action = parts[1], parts[2]
    if action not in ("login", "start", "complete", "review", "status"):
        return

    try:
        station_id = int(raw_station_id.removeprefix("station"))
    except ValueError:
        return

    if station_id not in station_states or raw_station_id != f"station{station_id:02d}":
        return

    current_state = station_states[station_id]
    # Status queries are read-only and independent of the allowed next action.
    if action == "status":
        if msg.payload.strip() == b"1":
            print(f"[STATUS REQUEST] Received from {raw_station_id} on {msg.topic}", flush=True)
            send_status(client, raw_station_id, current_state["team_id"], current_state["status"])
        # JSON replies on this same topic must not trigger another reply.
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
        send_status(client, raw_station_id, None, "error")
        return

    team_id = config.NFC_TEAMS.get(nfc_uuid)
    # Only the logged-in team can advance the station until review succeeds.
    if action != "login" and team_id != current_state["team_id"]:
        return

    if not isinstance(team_id, str) or not team_id.strip() or len(team_id) > 50:
        print("[ERROR] NFC UUID has no valid team mapping.", flush=True)
        send_status(client, raw_station_id, None, "error")
        return

    new_state = {"team_id": team_id, "status": action}
    if review_score is not None:
        new_state["review_score"] = review_score

    if not log_event_to_db(station_id, team_id, action, review_score):
        send_status(client, raw_station_id, team_id, "error")
        return

    station_states[station_id] = new_state
    # Confirm only after the review checks, DB commit, and state update succeed.
    status_sent = send_status(client, raw_station_id, team_id, action)
    print(f"[{action.upper()}] {team_id} at station {station_id}.", flush=True)
    if action == "review" and status_sent:
        send_next_station(client, station_id)
