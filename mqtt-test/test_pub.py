import json
import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

BROKER_IP = "127.0.0.1"
PORT = 1883

# --- Authentication Credentials ---
USERNAME = "station"  # Replace with your Mosquitto username
PASSWORD = "testen123"     # Replace with your Mosquitto password


def send_event(topic: str, team_id: str, station_id: int, status: str):
    client = mqtt.Client(CallbackAPIVersion.VERSION2)

    # Set credentials before connecting
    client.username_pw_set(USERNAME, PASSWORD)

    client.connect(BROKER_IP, PORT, 60)
    client.loop_start()

    payload = {
        "team_id": team_id,
        "station_id": station_id,
        "status": status,
    }

    print(f"\nSending to [{topic}]: {payload}")
    info = client.publish(topic, json.dumps(payload))
    info.wait_for_publish()  # Guarantees transmission before disconnect

    client.loop_stop()
    client.disconnect()
    print("Sent successfully!\n")


if __name__ == "__main__":
    print("=== MQTT Test Publisher ===")
    print("1: Station STARTED")
    print("2: Station COMPLETED")

    choice = input("Choose action (1 or 2): ").strip()
    team = input("Enter Team ID (e.g. Team-01): ").strip() or "Team-01"

    station_input = input("Enter Station ID (1-5): ").strip() or "1"
    station_id = int(station_input)

    if choice == "1":
        send_event("station/started", team, station_id, "started")
    elif choice == "2":
        send_event("station/completed", team, station_id, "completed")
    else:
        print("Invalid choice.")