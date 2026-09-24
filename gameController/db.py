from contextlib import closing

import psycopg2

from config import DB_CONFIG


def init_db():
    """Create the events table if it does not exist yet."""
    try:
        with closing(psycopg2.connect(**DB_CONFIG)) as conn:
            with conn, conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS station_events (
                        id SERIAL PRIMARY KEY,
                        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                        station_id VARCHAR(50) NOT NULL,
                        team_id VARCHAR(50) NOT NULL,
                        event_type VARCHAR(20) NOT NULL
                    );
                    ALTER TABLE station_events
                        ADD COLUMN IF NOT EXISTS review_score SMALLINT;
                """)
        print("[DB] PostgreSQL ready.", flush=True)
        return True
    except psycopg2.Error as exc:
        print(f"[DB ERROR] Initialization failed: {exc}", flush=True)
        return False


def log_event_to_db(station_id, team_id, event_type, review_score=None):
    """Save a station event and optional review score for Grafana."""
    # Game logic uses numeric IDs; event history uses the MQTT username.
    station_username = f"station{station_id:02d}"
    try:
        with closing(psycopg2.connect(**DB_CONFIG)) as conn:
            with conn, conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO station_events (station_id, team_id, event_type, review_score)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (station_username, team_id, event_type, review_score),
                )
        print(f"[DB LOG] {event_type}: {team_id} at {station_username}", flush=True)
        return True
    except psycopg2.Error as exc:
        print(f"[DB ERROR] Could not save event: {exc}", flush=True)
        return False
