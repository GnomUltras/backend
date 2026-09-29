"""Shared settings. The fallback values are used for local development.

For Docker, set environment variables such as MQTT_HOST=mosquitto
and DB_HOST=postgres.
"""

import os

# Broker settings shared by the controller, time service, and communication test.
MQTT_HOST = os.getenv("MQTT_HOST", "127.0.0.1")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER = os.getenv("MQTT_USER", "backend")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "testen123")
MQTT_TOPIC = os.getenv("MQTT_TOPIC", "station/#")
MQTT_CLIENT_ID = os.getenv("MQTT_CLIENT_ID", "game_controller")
MQTT_KEEPALIVE = int(os.getenv("MQTT_KEEPALIVE", "60"))

# Database connection used for persistent station state, results, and event history.
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "127.0.0.1"),
    "port": int(os.getenv("DB_PORT", "5432")),
    "dbname": os.getenv("DB_NAME", "stations"),
    "user": os.getenv("DB_USER", "stationuser"),
    "password": os.getenv("DB_PASSWORD", "changeme"),
    "connect_timeout": int(os.getenv("DB_CONNECT_TIMEOUT", "5")),
}

# Creates station IDs from station01 up to this count, also used for nextStation routing.
STATION_COUNT = int(os.getenv("STATION_COUNT", "5"))

# Team IDs and scanned identifiers are managed in PostgreSQL's team table.
