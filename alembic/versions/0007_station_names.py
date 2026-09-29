"""Rename the five stations to their assigned network IDs and game names.

Revision ID: 0007_station_names
Revises: 0006_team_identifiers
"""

from alembic import op
import sqlalchemy as sa

revision = "0007_station_names"
down_revision = "0006_team_identifiers"
branch_labels = None
depends_on = None

STATIONS = (
    ("station01", "station_2", "Morse"),
    ("station02", "station_3", "SQL"),
    ("station03", "station_4", "Password"),
    ("station04", "station_5", "JavaHOH"),
    ("station05", "station_6", "Quiz"),
)


def rename_station(source, destination, name):
    connection = op.get_bind()
    params = {"source": source, "destination": destination, "name": name}
    # Refuse ambiguous mixed catalogs instead of merging or discarding visits.
    if connection.execute(sa.text(
        "SELECT 1 FROM station WHERE station_id = :source"
    ), params).first() and connection.execute(sa.text(
        "SELECT 1 FROM station WHERE station_id = :destination"
    ), params).first():
        raise ValueError(f"Both {source} and {destination} exist; resolve the station mapping before migrating.")

    # Create the new parent first so all foreign keys remain valid while moving
    # results and live state. Timestamps, scores, rounds, and event IDs stay intact.
    connection.execute(sa.text(
        "INSERT INTO station (station_id, name) VALUES (:destination, :name) "
        "ON CONFLICT (station_id) DO UPDATE SET name = EXCLUDED.name"
    ), params)
    for table in ("results", "station_state", "station_events"):
        connection.execute(sa.text(
            f"UPDATE {table} SET station_id = :destination WHERE station_id = :source"
        ), params)
    connection.execute(sa.text("DELETE FROM station WHERE station_id = :source"), params)
    connection.execute(sa.text(
        "INSERT INTO station_state (station_id) VALUES (:destination) "
        "ON CONFLICT (station_id) DO NOTHING"
    ), params)


def upgrade():
    op.add_column("station", sa.Column("routing_order", sa.Integer(), nullable=False,
                                      server_default=sa.text("1000")))
    op.create_check_constraint("ck_station_routing_order", "station", "routing_order > 0")
    for routing_order, (old_id, station_id, name) in enumerate(STATIONS, start=1):
        rename_station(old_id, station_id, name)
        op.get_bind().execute(sa.text(
            "UPDATE station SET routing_order = :routing_order WHERE station_id = :station_id"
        ), {"routing_order": routing_order, "station_id": station_id})


def downgrade():
    op.drop_constraint("ck_station_routing_order", "station", type_="check")
    op.drop_column("station", "routing_order")
    for old_id, station_id, name in STATIONS:
        rename_station(station_id, old_id, old_id)
