import json
import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

BROKER_IP = "127.0.0.1" 
PORT = 1883
TOPIC = "station/#" 

# --- Authentication Credentials ---
USERNAME = "station"  # Replace with your Mosquitto username
PASSWORD = "testen123"     # Replace with your Mosquitto password

# State-Management: Trackt, welches Team an welcher Station ist (None = Frei)
stations_in_use = {1: None, 2: None, 3: None, 4: None, 5: None}

def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        print("Game Controller aktiv. Warte auf Station-Updates...", flush=True)
        client.subscribe(TOPIC)
    else:
        print(f"Verbindung fehlgeschlagen. Status-Code: {reason_code}", flush=True)

def on_message(client, userdata, msg):
    topic = msg.topic
    
    # 1. JSON Payload parsen
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
    except json.JSONDecodeError:
        print(f"[{topic}] Ignoriert: Kein gültiges JSON", flush=True)
        return

    team_id = payload.get("team_id")
    station_id = payload.get("station_id")

    # Abbruch, wenn wichtige Daten fehlen
    if not team_id or not isinstance(station_id, int):
        return

    # 2. Logik für 'station/started'
    if topic == "station/started":
        stations_in_use[station_id] = team_id
        print(f"[BELEGT] {team_id} arbeitet an Station {station_id}.")
        print(f"Aktuelle Auslastung: {stations_in_use}\n", flush=True)

    # 3. Logik für 'station/completed'
    elif topic == "station/completed":
        stations_in_use[station_id] = None
        
        # Round-Robin Berechnung: 1->2, 2->3, 3->4, 4->5, 5->1
        next_station = (station_id % 5) + 1
        
        print(f"[FERTIG] {team_id} hat Station {station_id} abgeschlossen.")
        print(f"[ROUTING] Sende {team_id} zu Station {next_station}...\n", flush=True)
        
        # 4. Routing-Befehl an das spezifische Team senden
        routing_payload = json.dumps({
            "team_id": team_id, 
            "next_station": next_station,
            "status": "move"
        })
        client.publish(f"team/{team_id}/route", routing_payload)


client = mqtt.Client(CallbackAPIVersion.VERSION2, client_id="game_controller")

# Set credentials before connecting
client.username_pw_set(USERNAME, PASSWORD)

client.on_connect = on_connect
client.on_message = on_message

client.connect(BROKER_IP, PORT, 60)
client.loop_forever()