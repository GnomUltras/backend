import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

import config
import communication_test
import servertime
from gameLogic import init_game, on_connect, on_message, on_publish


def main():
    if not init_game():
        return 1

    client = mqtt.Client(CallbackAPIVersion.VERSION2, client_id=config.MQTT_CLIENT_ID)
    client.username_pw_set(config.MQTT_USER, config.MQTT_PASSWORD)
    client.on_connect = on_connect
    client.on_message = on_message
    client.on_publish = on_publish

    time_client = None
    test_client = None
    try:
        time_client = servertime.start()
        test_client = communication_test.start()
        client.connect(config.MQTT_HOST, config.MQTT_PORT, config.MQTT_KEEPALIVE)
        client.loop_forever()
    except KeyboardInterrupt:
        print("Game Controller stopped.", flush=True)
    finally:
        client.disconnect()
        if test_client is not None:
            test_client.disconnect()
            test_client.loop_stop()
        if time_client is not None:
            time_client.disconnect()
            time_client.loop_stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
