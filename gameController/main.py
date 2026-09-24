import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

import config
from db import init_db
from gameLogic import on_connect, on_message, on_publish


def main():
    if not init_db():
        return 1

    client = mqtt.Client(CallbackAPIVersion.VERSION2, client_id=config.MQTT_CLIENT_ID)
    client.username_pw_set(config.MQTT_USER, config.MQTT_PASSWORD)
    client.on_connect = on_connect
    client.on_message = on_message
    client.on_publish = on_publish

    try:
        client.connect(config.MQTT_HOST, config.MQTT_PORT, config.MQTT_KEEPALIVE)
        client.loop_forever()
    except KeyboardInterrupt:
        print("Game Controller stopped.", flush=True)
    finally:
        client.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
