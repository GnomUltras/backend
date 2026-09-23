import json
import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

# --- Konfiguration ---
BROKER_IP = "127.0.0.1"
PORT = 1883
STATION_ID = "station01"
TOPIC = f"station/{STATION_ID}/servertime"

# Username must fit to the ACL (z. B. "station-01")
MQTT_USER = str(STATION_ID)
MQTT_PASS = "testen123"


def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        print(f"[STATION {STATION_ID}] Verbunden mit Broker.", flush=True)

        # subscribe to topic to get repsonse from backend
        client.subscribe(TOPIC, qos=1)

        # send GET request
        request_payload = {"request": "GET"}
        print(f"[STATION {STATION_ID}] Sende GET-Anfrage an [{TOPIC}]...", flush=True)
        client.publish(TOPIC, json.dumps(request_payload), qos=1)
    else:
        print(f"[STATION {STATION_ID}] Verbindung fehlgeschlagen: {reason_code}", flush=True)


def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
    except json.JSONDecodeError:
        return

    # only process when response type is POST
    if payload.get("request") == "POST":
        print("\n=====================================", flush=True)
        print("  SERVERTIME ANTWORT EMPFANGEN", flush=True)
        print("=====================================", flush=True)
        print(f"Raw Payload : {msg.payload.decode('utf-8')}", flush=True)
        print(f"Server-Zeit : {payload.get('server_time')}", flush=True)
        print(f"Unix Epoche : {payload.get('unix')}", flush=True)
        print("=====================================\n", flush=True)

        client.disconnect()


if __name__ == "__main__":
    client = mqtt.Client(CallbackAPIVersion.VERSION2, client_id=f"station_{STATION_ID}_emulator")
    client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.on_connect = on_connect
    client.on_message = on_message

    client.connect(BROKER_IP, PORT, 60)
    client.loop_forever()