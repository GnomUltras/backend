import json
import time
import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

BROKER_IP = "127.0.0.1"
PORT = 1883

team_id = input("Enter Team ID for this simulator (e.g. Team-01): ").strip() or "Team-01"


def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        print(f"\n[CONNECTED] Listening for routing updates on 'team/{team_id}/route'...\n", flush=True)
        client.subscribe(f"team/{team_id}/route")


def on_message(client, userdata, msg):
    """Triggers whenever the Game Controller sends a route command to this team."""
    try:
        data = json.loads(msg.payload.decode("utf-8"))
        status = data.get("status").upper()
        target = data.get("target_station")
        message = data.get("message", "")

        print("\n" + "=" * 50)
        print(f" INCOMING ROUTE COMMAND FOR {team_id}")
        print(f" STATUS:  {status}")
        print(f" TARGET:  Station {target}")
        print(f" MESSAGE: {message}")
        print("=" * 50 + "\nChoice: ", end="", flush=True)
    except Exception as e:
        print(f"\nError decoding payload: {e}")


client = mqtt.Client(CallbackAPIVersion.VERSION2, client_id=f"sim_{team_id}")
client.on_connect = on_connect
client.on_message = on_message

client.connect(BROKER_IP, PORT, 60)
client.loop_start()

try:
    while True:
        print(f"\n--- Menu ({team_id}) ---")
        print("1: Send 'station/started'")
        print("2: Send 'station/completed'")
        print("q: Quit")
        choice = input("Choice: ").strip()

        if choice.lower() == "q":
            break

        if choice in ["1", "2"]:
            station_input = input("Station ID (1-5): ").strip() or "1"
            station_id = int(station_input)

            if choice == "1":
                topic = "station/started"
                payload = {"team_id": team_id, "station_id": station_id, "status": "started"}
            else:
                topic = "station/completed"
                payload = {"team_id": topic, "station_id": station_id, "status": "completed"}
                payload["team_id"] = team_id

            client.publish(topic, json.dumps(payload))
            print(f"Sent [{topic}] for Station {station_id}")
        
        time.sleep(0.2)

finally:
    client.loop_stop()
    client.disconnect()
    print("Simulator closed.")