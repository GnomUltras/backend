"""Request and display the server's Berlin time over MQTT."""

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


def request_servertime(station_id):
    topic = f"station/{station_id}/servertime"
    finished = Event()
    response = None

    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code != 0:
            print(f"[ERROR] Connection failed: {reason_code}", flush=True)
            finished.set()
            return
        result, _ = client.subscribe(topic, qos=1)
        if result != mqtt.MQTT_ERR_SUCCESS:
            print(f"[ERROR] Could not subscribe: {result}", flush=True)
            finished.set()

    def on_subscribe(client, userdata, mid, reason_codes, properties):
        if any(code.is_failure for code in reason_codes):
            print("[ERROR] Server-time subscription rejected.", flush=True)
            finished.set()
            return
        # Wait for SUBACK so a fast reply cannot arrive before we are listening.
        result = client.publish(topic, json.dumps({"request": "GET"}), qos=1, retain=False)
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            print(f"[ERROR] Could not request server time: {result.rc}", flush=True)
            finished.set()
            return
        print(f"[REQUEST] Sent time request to {topic}", flush=True)

    def on_message(client, userdata, msg):
        nonlocal response
        if finished.is_set() or msg.topic != topic or msg.retain:
            return
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return
        # The broker also echoes our GET request on this topic.
        if not isinstance(payload, dict) or payload.get("request") != "POST":
            return
        if not isinstance(payload.get("server_time"), str) or type(payload.get("unix")) is not int:
            return
        response = payload
        print(f"[BERLIN TIME] {payload['server_time']}", flush=True)
        print(f"[UNIX] {payload['unix']}", flush=True)
        finished.set()

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.connect_timeout = RESPONSE_TIMEOUT
    client.username_pw_set(station_id, MQTT_PASSWORD)
    client.on_connect = on_connect
    client.on_subscribe = on_subscribe
    client.on_message = on_message

    try:
        client.connect(MQTT_HOST, MQTT_PORT, 60)
        client.loop_start()
        if not finished.wait(RESPONSE_TIMEOUT):
            print(f"[TIMEOUT] No server-time reply within {RESPONSE_TIMEOUT:g} seconds.", flush=True)
    except OSError as exc:
        print(f"[ERROR] Could not connect to {MQTT_HOST}:{MQTT_PORT}: {exc}", flush=True)
    finally:
        client.disconnect()
        client.loop_stop()
    return response


if __name__ == "__main__":
    station_id = input(f"Station ID [{STATION_ID}]: ").strip() or STATION_ID
    raise SystemExit(0 if request_servertime(station_id) is not None else 1)
