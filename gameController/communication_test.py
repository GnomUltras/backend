"""Reply to plain MQTT communication checks without touching game state."""

import paho.mqtt.client as mqtt

import config


TOPIC = "station/+/test"


def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code != 0:
        print(f"[TEST SERVICE] Connection rejected: {reason_code}", flush=True)
        return
    client.subscribe(TOPIC, qos=1)


def on_message(client, userdata, msg):
    parts = msg.topic.split("/")
    if msg.retain or len(parts) != 3 or parts[0] != "station" or not parts[1] or parts[2] != "test":
        return
    # Only 1 is a request. Ignore our own 2 replies on this shared topic.
    if msg.payload != b"1":
        return
    result = client.publish(msg.topic, "2", qos=1, retain=False)
    print(f"[TEST] Communication test successful.", flush=True)
    if result.rc != mqtt.MQTT_ERR_SUCCESS:
        print(f"[TEST SERVICE] Could not publish reply: {result.rc}", flush=True)


def create_client():
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"{config.MQTT_CLIENT_ID}_communication_test",
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
        raise RuntimeError(f"Could not start communication test service: {result}")
    return client


def main():
    client = create_client()
    try:
        client.loop_forever(retry_first_connection=True)
    except KeyboardInterrupt:
        print("[TEST SERVICE] Stopped.", flush=True)
    finally:
        client.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
