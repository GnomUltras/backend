"""Send plain 1 and wait for plain 2 on the station's test topic."""

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


def test_communication(station_id):
    topic = f"station/{station_id}/test"
    finished = Event()
    received_reply = False

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
            print("[ERROR] Test subscription rejected.", flush=True)
            finished.set()
            return
        # Wait for SUBACK so we are listening before the service can reply.
        result = client.publish(topic, "1", qos=1, retain=False)
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            print(f"[ERROR] Could not send test request: {result.rc}", flush=True)
            finished.set()

    def on_message(client, userdata, msg):
        nonlocal received_reply
        if finished.is_set() or msg.topic != topic or msg.retain or msg.payload != b"2":
            return
        received_reply = True
        print("2", flush=True)
        finished.set()

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.connect_timeout = RESPONSE_TIMEOUT
    client.username_pw_set(station_id, MQTT_PASSWORD)
    client.on_connect = on_connect
    client.on_subscribe = on_subscribe
    client.on_message = on_message

    try:
        client.connect(MQTT_HOST, MQTT_PORT, 60)
        result = client.loop_start()
        if result != mqtt.MQTT_ERR_SUCCESS:
            print(f"[ERROR] Could not start MQTT client: {result}", flush=True)
        elif not finished.wait(RESPONSE_TIMEOUT):
            print(f"[TIMEOUT] No test reply within {RESPONSE_TIMEOUT:g} seconds.", flush=True)
    except OSError as exc:
        print(f"[ERROR] Could not connect to {MQTT_HOST}:{MQTT_PORT}: {exc}", flush=True)
    finally:
        client.disconnect()
        client.loop_stop()
    return received_reply


if __name__ == "__main__":
    station_id = input(f"Station ID [{STATION_ID}]: ").strip() or STATION_ID
    raise SystemExit(0 if test_communication(station_id) else 1)
