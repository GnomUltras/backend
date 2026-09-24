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
    finished = Event()
    response = None

    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code != 0:
            print(f"[ERROR] Connection failed: {reason_code}", flush=True)
            finished.set()
            return
        client.subscribe(topic, qos=1)

    def on_subscribe(client, userdata, mid, reason_codes, properties):
        if any(code.is_failure for code in reason_codes):
            print("[ERROR] Status subscription rejected.", flush=True)
            finished.set()
            return
        result = client.publish(topic, "1", qos=1, retain=False)
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            print(f"[ERROR] Could not query status: {result.rc}", flush=True)
            finished.set()
            return
        print(f"[QUERY] Sent 1 to {topic}", flush=True)

    def on_message(client, userdata, msg):
        nonlocal response
        if msg.topic != topic or msg.retain:
            return
        try:
            status = json.loads(msg.payload.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return
        # Ignore the echoed plain "1" and accept only JSON status replies.
        if not isinstance(status, dict) or "team_id" not in status:
            return
        if status.get("status") not in ("idle", "login", "start", "complete", "review", "error"):
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


if __name__ == "__main__":
    station_id = input(f"Station ID [{STATION_ID}]: ").strip() or STATION_ID
    request_status(station_id)
