import json
import os
from threading import Event

import paho.mqtt.client as mqtt


MQTT_HOST = os.getenv("MQTT_HOST", "127.0.0.1")
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
    payload = nfc_uuid.strip()
    if action == "review":
        if type(review_score) is not int or review_score not in (0, 1, 2):
            raise ValueError("Review score must be 0, 1, or 2.")
        payload = f"{payload};{review_score}"
    finished = Event()
    response = None

    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code != 0:
            print(f"[ERROR] Connection failed: {reason_code}", flush=True)
            finished.set()
            return
        client.subscribe(status_topic, qos=1)

    def on_subscribe(client, userdata, mid, reason_codes, properties):
        if any(code.is_failure for code in reason_codes):
            print("[ERROR] Status subscription rejected.", flush=True)
            finished.set()
            return
        # Send only after the broker confirms the status subscription.
        result = client.publish(topic, payload, qos=1, retain=False)
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            print(f"[ERROR] Could not send request: {result.rc}", flush=True)
            finished.set()
            return
        print(f"[REQUEST] Sent to {topic}: {payload}", flush=True)

    def on_message(client, userdata, msg):
        nonlocal response
        if msg.topic != status_topic or msg.retain:
            return
        try:
            status = json.loads(msg.payload.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return
        # The team name is resolved by the controller, not by this client.
        if not isinstance(status, dict):
            return
        if status.get("status") not in (action, "error"):
            return
        response = status
        print(f"[STATUS] Received from {msg.topic}: {json.dumps(status)}", flush=True)
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
            print(f"[TIMEOUT] No status reply within {RESPONSE_TIMEOUT:g} seconds.", flush=True)
    finally:
        client.disconnect()
        client.loop_stop()
    return response


def send_login(station_id, nfc_uuid):
    return send_request(station_id, nfc_uuid, "login")


if __name__ == "__main__":
    station_id = input(f"Station ID [{STATION_ID}]: ").strip() or STATION_ID
    nfc_uuid = input(f"NFC UUID [{NFC_UUID}]: ").strip() or NFC_UUID
    action = input("Action (login/start/complete/review) [login]: ").strip().lower() or "login"
    review_score = None
    if action == "review":
        review_score = int(input("Review score (0/1/2) [1]: ").strip() or "1")
    send_request(station_id, nfc_uuid, action, review_score)
