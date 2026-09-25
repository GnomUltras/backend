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
RESPONSE_TIMEOUT = float(os.getenv("RESPONSE_TIMEOUT", "5"))


def send_request(station_id, nfc_uuid, action="login", review_score=None):
    if action not in ("login", "start", "complete", "review"):
        raise ValueError("Action must be login, start, complete, or review.")
    if not isinstance(nfc_uuid, str) or not nfc_uuid.strip():
        raise ValueError("NFC UUID must not be empty.")

    topic = f"station/{station_id}/{action}"
    status_topic = f"station/{station_id}/status"
    next_station_topic = f"station/{station_id}/nextStation"
    request = {"nfc_uuid": nfc_uuid.strip()}
    if action == "review":
        if type(review_score) is not int or review_score not in (0, 1, 2):
            raise ValueError("Review score must be 0, 1, or 2.")
        request["review_score"] = review_score
    payload = json.dumps(request)
    finished = Event()
    response = None
    next_station = None

    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code != 0:
            print(f"[ERROR] Connection failed: {reason_code}", flush=True)
            finished.set()
            return
        topics = [(status_topic, 1)]
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
        nonlocal response, next_station
        if msg.retain:
            return
        try:
            text = msg.payload.decode("utf-8")
            if action == "review" and msg.topic == next_station_topic:
                next_station = text.strip()
                if next_station:
                    print(f"[NEXT STATION] Received from {msg.topic}: {next_station}", flush=True)
                    if response is not None and response["status"] == "review":
                        finished.set()
                return
            if msg.topic != status_topic:
                return
            status = json.loads(text)
        except (ValueError, UnicodeDecodeError):
            return
        # The team name is resolved by the controller, not by this client.
        if not isinstance(status, dict):
            return
        if status.get("status") not in (action, "error"):
            return
        response = status
        print(f"[STATUS] Received from {msg.topic}: {json.dumps(status)}", flush=True)
        if status["status"] == "error" or action != "review" or next_station:
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
            expected = "review status and next-station destination" if action == "review" else "status reply"
            print(f"[TIMEOUT] Did not receive {expected} within {RESPONSE_TIMEOUT:g} seconds.", flush=True)
            return None
    finally:
        client.disconnect()
        client.loop_stop()
    if response is not None and response["status"] == "review" and next_station:
        return {**response, "next_station": next_station}
    return response


def send_login(station_id, nfc_uuid):
    return send_request(station_id, nfc_uuid, "login")


if __name__ == "__main__":
    station_id = input(f"Station ID [{STATION_ID}]: ").strip() or STATION_ID
    action = input("Action (login/start/complete/review) [login]: ").strip().lower() or "login"
    nfc_uuid = input(f"NFC UUID [{NFC_UUID}]: ").strip() or NFC_UUID
    review_score = None
    if action == "review":
        review_score = int(input("Review score (0/1/2) [1]: ").strip() or "1")
    send_request(station_id, nfc_uuid, action, review_score)
