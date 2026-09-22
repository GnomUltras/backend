import json
import time
from datetime import datetime, timezone
import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

# --- Network & Credentials ---
BROKER_IP = "127.0.0.1"
PORT = 1883
MQTT_USER = "backend"
MQTT_PASS = "testen123"

# Wildcard '+', so EVERY station can request etc (z.B. station/1/servertime, station/2/servertime)
TOPIC_LISTEN = "station/+/servertime"


def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        print("[TIME SERVICE] Aktiv und bereit für Time-Requests.", flush=True)
        client.subscribe(TOPIC_LISTEN, qos=1)
    else:
        print(f"[TIME SERVICE] Verbindung fehlgeschlagen: {reason_code}", flush=True)


def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
    except json.JSONDecodeError:
        return

    # only respond when "request": "GET"
    if payload.get("request") == "GET":
        now = datetime.now(timezone.utc)

        response_payload = {
            "request": "POST",
            "server_time": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "unix": int(now.timestamp())
        }

        # send response on the same topic with qos=1 to ensure delivery
        client.publish(msg.topic, json.dumps(response_payload), qos=1)
        print(f"[TIME SERVICE] Zeitstempel gesendet an [{msg.topic}]", flush=True)


if __name__ == "__main__":
    client = mqtt.Client(CallbackAPIVersion.VERSION2, client_id="backend_time_service")
    client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.on_connect = on_connect
    client.on_message = on_message

    client.connect(BROKER_IP, PORT, 60)
    
    client.loop_forever()