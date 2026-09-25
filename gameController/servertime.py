"""Reply to MQTT time requests using Europe/Berlin local time."""

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import paho.mqtt.client as mqtt

import config


TOPIC = "station/+/servertime"
BERLIN = ZoneInfo("Europe/Berlin")


def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code != 0:
        print(f"[TIME SERVICE] Connection rejected: {reason_code}", flush=True)
        return
    client.subscribe(TOPIC, qos=1)
    print(f"[TIME SERVICE] Listening on {TOPIC} (Europe/Berlin).", flush=True)


def on_message(client, userdata, msg):
    parts = msg.topic.split("/")
    if msg.retain or len(parts) != 3 or parts[0] != "station" or not parts[1] or parts[2] != "servertime":
        return
    try:
        request = json.loads(msg.payload.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return
    # Ignore our own POST replies and malformed requests on the shared topic.
    if not isinstance(request, dict) or request.get("request") != "GET":
        return

    now = datetime.now(BERLIN)
    response = {
        "request": "POST",
        "server_time": now.isoformat(timespec="seconds"),
        "unix": int(now.timestamp()),
    }
    result = client.publish(msg.topic, json.dumps(response), qos=1, retain=False)
    if result.rc != mqtt.MQTT_ERR_SUCCESS:
        print(f"[TIME SERVICE] Could not publish reply: {result.rc}", flush=True)


def create_client():
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"{config.MQTT_CLIENT_ID}_servertime",
    )
    client.username_pw_set(config.MQTT_USER, config.MQTT_PASSWORD)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect_async(config.MQTT_HOST, config.MQTT_PORT, config.MQTT_KEEPALIVE)
    return client


def start():
    """Start an independent MQTT network thread alongside the game controller."""
    client = create_client()
    result = client.loop_start()
    if result != mqtt.MQTT_ERR_SUCCESS:
        raise RuntimeError(f"Could not start time service: {result}")
    return client


def main():
    client = create_client()
    try:
        client.loop_forever(retry_first_connection=True)
    except KeyboardInterrupt:
        print("[TIME SERVICE] Stopped.", flush=True)
    finally:
        client.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
