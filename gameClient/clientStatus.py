"""Query a station's current status without sending a game action."""

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
RESPONSE_TIMEOUT = float(os.getenv("RESPONSE_TIMEOUT", "5"))


def request_status(station_id):
    topic = f"station/{station_id}/status"
    error_topic = f"station/{station_id}/error"
    finished = Event()
    response = None
    acknowledgement = None

    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code != 0:
            print(f"[ERROR] Connection failed: {reason_code}", flush=True)
            finished.set()
            return
        client.subscribe([(topic, 1), (error_topic, 1)])

    def on_subscribe(client, userdata, mid, reason_codes, properties):
        if any(code.is_failure for code in reason_codes):
            print("[ERROR] Status subscription rejected.", flush=True)
            finished.set()
            return
        payload = json.dumps({"request": "GET"})
        result = client.publish(topic, payload, qos=1, retain=False)
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            print(f"[ERROR] Could not query status: {result.rc}", flush=True)
            finished.set()
            return
        print(f"[QUERY] Sent {payload} to {topic}", flush=True)

    def on_message(client, userdata, msg):
        nonlocal response, acknowledgement
        if msg.retain:
            return
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return
        if not isinstance(payload, dict):
            return
        if msg.topic == error_topic and payload.get("action") == "status":
            if payload.get("return") not in ("OK", "ERROR"):
                return
            acknowledgement = payload
            if payload["return"] == "ERROR":
                print(f"[ERROR] {json.dumps(payload)}", flush=True)
                finished.set()
                return
        elif msg.topic == topic and "team_id" in payload:
            if payload.get("status") not in ("idle", "logged_in", "running", "reviewing"):
                return
            response = payload
            print(f"[STATUS] {json.dumps(payload)}", flush=True)
        if (response is not None and acknowledgement is not None and acknowledgement["return"] == "OK"
                and "team_id" in acknowledgement and acknowledgement["team_id"] == response["team_id"]):
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
            print(f"[TIMEOUT] Missing status or OK within {RESPONSE_TIMEOUT:g} seconds.", flush=True)
            return None
    finally:
        client.disconnect()
        client.loop_stop()
    if acknowledgement is not None and acknowledgement["return"] == "ERROR":
        return acknowledgement
    return response


if __name__ == "__main__":
    station_id = input(f"Station ID [{STATION_ID}]: ").strip() or STATION_ID
    request_status(station_id)
