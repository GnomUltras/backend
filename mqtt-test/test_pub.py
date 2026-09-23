import json
import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

BROKER_IP = "127.0.0.1"  # Lokaler MQTT-Broker
PORT = 1883
PASSWORD = "testen123"


def send_event(topic: str, team_id: str, station_id: int, status: str, username: str):
    client = mqtt.Client(CallbackAPIVersion.VERSION2)

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
    info.wait_for_publish()

    client.loop_stop()
    client.disconnect()
    print("Sent successfully!\n")


if __name__ == "__main__":
    print("=== MQTT Test Publisher ===")
    print("1: Station START")
    print("2: Station COMPLETE")

    choice = input("Choose action (1 or 2): ").strip()
    team = input("Enter Team ID (e.g. Team-01): ").strip() or "Team-01"

    # Station Nummer abfragen (1-5)
    station_input = input("Enter Station Number (1-5): ").strip() or "1"
    try:
        station_num = int(station_input)
        if not (1 <= station_num <= 5):
            station_num = 1
    except ValueError:
        station_num = 1

    # Formatierung: 1 -> "01", 2 -> "02" etc.
    station_str = f"{station_num:02d}"
    username = f"station{station_str}"  # z.B. station01

    # Topic und Username sind nun synchron mit der ACL: station/<username>/start
    if choice == "1":
        topic = f"station/{username}/start"
        send_event(topic, team, station_num, "started", username)
    elif choice == "2":
        topic = f"station/{username}/complete"
        send_event(topic, team, station_num, "completed", username)
    else:
        print("Invalid choice.")