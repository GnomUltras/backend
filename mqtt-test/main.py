import json
import psycopg2
import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

# --- Network & Credentials ---
BROKER_IP = "127.0.0.1"  # Raspberry Pi IP (or "192.168.1.11" for local testing)
PORT = 1883
TOPIC = "station/#"

MQTT_USER = "backend"
MQTT_PASS = "testen123"

# --- Database Config ---
DB_HOST = "127.0.0.1"   # IP where PostgreSQL is running
DB_PORT = 5432
DB_NAME = "stations"
DB_USER = "stationuser"
DB_PASS = "changeme"

# State Tracking
stations_in_use = {1: None, 2: None, 3: None, 4: None, 5: None}


def init_db():
    """Creates the events table in PostgreSQL if it doesn't exist yet."""
    try:
        conn = psycopg2.connect(
            host=DB_HOST, port=DB_PORT, dbname=DB_NAME, user=DB_USER, password=DB_PASS
        )
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS station_events (
                id SERIAL PRIMARY KEY,
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                station_id INT NOT NULL,
                team_id VARCHAR(50) NOT NULL,
                event_type VARCHAR(20) NOT NULL
            );
        """)
        conn.commit()
        cur.close()
        conn.close()
        print("[DB] PostgreSQL database initialized successfully.", flush=True)
    except Exception as e:
        print(f"[DB ERROR] Could not initialize database: {e}", flush=True)


def log_event_to_db(station_id: int, team_id: str, event_type: str):
    """Inserts a station event into PostgreSQL."""
    try:
        conn = psycopg2.connect(
            host=DB_HOST, port=DB_PORT, dbname=DB_NAME, user=DB_USER, password=DB_PASS
        )
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO station_events (station_id, team_id, event_type)
            VALUES (%s, %s, %s)
            """,
            (station_id, team_id, event_type)
        )
        conn.commit()
        cur.close()
        conn.close()
        print(f"[DB LOG] Logged '{event_type}' for {team_id} at Station {station_id}", flush=True)
    except Exception as e:
        print(f"[DB ERROR] Failed to insert event: {e}", flush=True)


def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        print("Game Controller aktiv. Warte auf Station-Updates...", flush=True)
        client.subscribe(TOPIC)
    else:
        print(f"Verbindung fehlgeschlagen: {reason_code}", flush=True)


def on_message(client, userdata, msg):
    parts = msg.topic.split("/")
    if len(parts) < 3:
        return

    raw_station_id, action = parts[1], parts[2]

    try:
        clean_id = raw_station_id.replace("station", "")
        station_id = int(clean_id)
    except ValueError:
        return

    try:
        payload = json.loads(msg.payload.decode("utf-8"))
    except json.JSONDecodeError:
        return

    team_id = payload.get("team_id")
    if not team_id:
        return

    # --- EVENT: START ---
    if action == "start":
        stations_in_use[station_id] = team_id
        print(f"[BELEGT] {team_id} an Station {station_id}.", flush=True)
        
        # Log to DB
        log_event_to_db(station_id, team_id, "start")

    # --- EVENT: COMPLETE ---
    elif action == "complete":
        stations_in_use[station_id] = None
        next_station = (station_id % 5) + 1
        
        print(f"[FERTIG] {team_id} an Station {station_id}.", flush=True)

        # Log to DB
        log_event_to_db(station_id, team_id, "complete")

        # Routing command
        routing_payload = json.dumps({"team_id": team_id, "next_station": next_station, "status": "move"})
        client.publish("backend/timestamp", routing_payload)


# inititalize db on startup
init_db()

# Setup MQTT Client
client = mqtt.Client(CallbackAPIVersion.VERSION2, client_id="game_controller")
client.username_pw_set(MQTT_USER, MQTT_PASS)
client.on_connect = on_connect
client.on_message = on_message

client.connect(BROKER_IP, PORT, 60)
client.loop_forever()