import json
import os
from threading import Event

import paho.mqtt.client as mqtt


# Local script / local Docker: "localhost"; Docker on the Pi: "192.168.1.11"
MQTT_HOST = "localhost"
# MQTT_HOST = "192.168.1.11"
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "testen123")
STATION_ID = os.getenv("STATION_ID", "station01")
NFC_UUID = os.getenv("NFC_UUID", "AA BB CC 01")
TEAM_ID = os.getenv("TEAM_ID", "Team-01")
ACTION_STATE = {"login": "logged_in", "start": "running", "complete": "reviewing", "review": "idle"}
RESPONSE_TIMEOUT = float(os.getenv("RESPONSE_TIMEOUT", "5"))


def send_request(station_id, identifier, action="login", review_score=None):
    if action not in ("login", "start", "complete", "review"):
        raise ValueError("Action must be login, start, complete, or review.")
    if not isinstance(identifier, str) or not identifier.strip():
        raise ValueError("UUID (login) or team ID (other actions) must not be empty.")
    identifier = identifier.strip()

    topic = f"station/{station_id}/{action}"
    error_topic = f"station/{station_id}/error"
    status_topic = f"station/{station_id}/status"
    next_station_topic = f"station/{station_id}/nextStation"
    request = {"uuid" if action == "login" else "team_id": identifier}
    if action == "review":
        if type(review_score) is not int or review_score not in (0, 1, 2):
            raise ValueError("Review score must be 0, 1, or 2.")
        request["score"] = review_score
    payload = json.dumps(request)
    finished = Event()
    response = None
    routing = None
    acknowledgement = None

    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code != 0:
            print(f"[ERROR] Connection failed: {reason_code}", flush=True)
            finished.set()
            return
        topics = [(status_topic, 1), (error_topic, 1)]
        if action == "review":
            topics.append((next_station_topic, 1))
        client.subscribe(topics)

    def on_subscribe(client, userdata, mid, reason_codes, properties):
        if any(code.is_failure for code in reason_codes):
            print("[ERROR] Reply subscription rejected.", flush=True)
            finished.set()
            return
        # Listen for the automatic reply before sending the action.
        result = client.publish(topic, payload, qos=1, retain=False)
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            print(f"[ERROR] Could not send request: {result.rc}", flush=True)
            finished.set()
            return
        print(f"[REQUEST] Sent to {topic}: {payload}", flush=True)

    def on_message(client, userdata, msg):
        nonlocal response, routing, acknowledgement
        if msg.retain:
            return
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return
        if not isinstance(payload, dict):
            return
        if msg.topic == error_topic:
            if payload.get("action") != action or payload.get("return") not in ("OK", "ERROR"):
                return
            if "team_id" not in payload:
                return
            # Rejections before team resolution have no team. Otherwise an ACK
            # for another team must never finish our pending action.
            if action != "login" and payload["team_id"] != identifier:
                if payload["return"] != "ERROR" or payload["team_id"] is not None:
                    return
            acknowledgement = payload
            print(f"[RETURN] {json.dumps(payload)}", flush=True)
            if payload["return"] == "ERROR":
                finished.set()
                return
        elif msg.topic == next_station_topic and action == "review":
            if payload.get("team_id") != identifier:
                return
            destination = payload.get("next_station")
            route_status = payload.get("routing_status")
            if type(payload.get("round")) is not int or payload["round"] < 1:
                return
            if route_status in ("available", "queued"):
                if not isinstance(destination, str) or not destination:
                    return
            elif route_status in ("round_complete", "no_available_station"):
                if "next_station" not in payload or destination is not None:
                    return
            else:
                return
            routing = {key: payload[key] for key in ("next_station", "routing_status", "round")}
            print(f"[NEXT STATION] {json.dumps(payload)}", flush=True)
        elif msg.topic == status_topic:
            if payload.get("status") != ACTION_STATE[action] or "team_id" not in payload:
                return
            if action == "login" and (not isinstance(payload["team_id"], str) or not payload["team_id"]):
                return
            if action != "login" and payload["team_id"] != (None if action == "review" else identifier):
                return
            response = payload
            print(f"[STATUS] {json.dumps(payload)}", flush=True)
        else:
            return
        # Replies may arrive in any order. /status alone is not an acknowledgement.
        if (acknowledgement is not None and acknowledgement.get("return") == "OK"
                and response is not None and (action != "review" or routing is not None)
                and acknowledgement["team_id"] == (identifier if action == "review" else response["team_id"])):
            finished.set()

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.username_pw_set(station_id, MQTT_PASSWORD)
    client.on_connect = on_connect
    client.on_subscribe = on_subscribe
    client.on_message = on_message

    try:
        client.connect(MQTT_HOST, MQTT_PORT, 60)
        client.loop_start()
        if not finished.wait(RESPONSE_TIMEOUT):
            expected = "idle status, OK, and next-station destination" if action == "review" else "status and OK"
            print(f"[TIMEOUT] Did not receive {expected} within {RESPONSE_TIMEOUT:g} seconds.", flush=True)
            return None
    finally:
        client.disconnect()
        client.loop_stop()
    if acknowledgement is not None and acknowledgement["return"] == "ERROR":
        return acknowledgement
    if response is None or acknowledgement is None:
        return None
    return {**acknowledgement, **response, **(routing or {})}


def send_login(station_id, nfc_uuid):
    return send_request(station_id, nfc_uuid, "login")


if __name__ == "__main__":
    station_id = input(f"Station ID [{STATION_ID}]: ").strip() or STATION_ID
    action = input("Action (login/start/complete/review) [login]: ").strip().lower() or "login"
    label, default = ("NFC UUID", NFC_UUID) if action == "login" else ("Team ID", TEAM_ID)
    identifier = input(f"{label} [{default}]: ").strip() or default
    review_score = None
    if action == "review":
        review_score = int(input("Review score (0/1/2) [1]: ").strip() or "1")
    send_request(station_id, identifier, action, review_score)
