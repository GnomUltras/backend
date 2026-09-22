import json
import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

BROKER_IP = "127.0.0.1"  # Lokaler MQTT-Broker (oder "192.168.1.11")
PORT = 1883
PASSWORD = "testen123"


def send_event(topic: str, team_id: str, station_id: int, status: str, username: str):
    client = mqtt.Client(CallbackAPIVersion.VERSION2)

    # Benutzername dynamisch setzen, damit er zur ACL passt
    client.username_pw_set(username, PASSWORD)

    client.connect(BROKER_IP, PORT, 60)
    client.loop_start()

    payload = {
        "team_id": team_id,
        "station_id": station_id,
        "status": status,
    }

    print(f"\nSending to [{topic}] as user '{username}': {payload}")
    info = client.publish(topic, json.dumps(payload))
    info.wait_for_publish()  # Garantiert die Übertragung vor dem Disconnect

    client.loop_stop()
    client.disconnect()
    print("Sent successfully!\n")


if __name__ == "__main__":
    print("=== MQTT Test Publisher ===")
    print("1: Station START")
    print("2: Station COMPLETE")

    choice = input("Choose action (1 or 2): ").strip()
    team = input("Enter Team ID (e.g. Team-01): ").strip() or "Team-01"

    station_input = input("Enter Station ID (1-5): ").strip() or "1"
    try:
        station_id = int(station_input)
    except ValueError:
        station_id = 1

    # Username passend zur ACL eingeben (z. B. "station01" oder "5")
    default_user = f"station0{station_id}"
    username = input(f"Enter Username (Default: {default_user}): ").strip() or default_user

    # Dynamischer Topic-Aufbau: station/<station_id>/start bzw. complete
    if choice == "1":
        topic = f"station/{station_id}/start"
        send_event(topic, team, station_id, "started", username)
    elif choice == "2":
        topic = f"station/{station_id}/complete"
        send_event(topic, team, station_id, "completed", username)
    else:
        print("Invalid choice.")