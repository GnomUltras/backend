"""Shared settings. The fallback values are used for local development.

For Docker, set environment variables such as MQTT_HOST=mosquitto
and DB_HOST=postgres.
"""

import os

# MQTT
MQTT_HOST = os.getenv("MQTT_HOST", "127.0.0.1")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER = os.getenv("MQTT_USER", "backend")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "testen123")
MQTT_TOPIC = os.getenv("MQTT_TOPIC", "station/#")
MQTT_CLIENT_ID = os.getenv("MQTT_CLIENT_ID", "game_controller")
MQTT_KEEPALIVE = int(os.getenv("MQTT_KEEPALIVE", "60"))

# PostgreSQL
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "127.0.0.1"),
    "port": int(os.getenv("DB_PORT", "5432")),
    "dbname": os.getenv("DB_NAME", "stations"),
    "user": os.getenv("DB_USER", "stationuser"),
    "password": os.getenv("DB_PASSWORD", "changeme"),
}

# Game
STATION_COUNT = int(os.getenv("STATION_COUNT", "5"))

# Example NFC UUIDs for local testing. Replace these with the actual chip IDs.
NFC_TEAMS = {
    "AA BB CC 01": "Team-01",
    "AA BB CC 02": "Team-02",
    "AA BB CC 03": "Team-03",
    "AA BB CC 04": "Team-04",
    "AA BB CC 05": "Team-05",
}
