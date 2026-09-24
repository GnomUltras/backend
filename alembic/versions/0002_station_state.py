"""Add current station state and adopt the existing Grafana event history.

Revision ID: 0002_station_state
Revises: 0001_init
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_station_state"
down_revision = "0001_init"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # NFC UUIDs are resolved in config.py; only team names belong in game state.
    op.drop_column("team", "signature")
    op.create_unique_constraint("uq_team_name", "team", ["name"])

    # One row per station, independent of how many teams have visited it.
    op.create_table(
        "station_state",
        sa.Column("station_id", sa.Integer(), primary_key=True),
        sa.Column("team_name", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="idle"),
        sa.Column("review_score", sa.SmallInteger(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["station_id"], ["station.station_id"], name="fk_station_state_station"
        ),
        sa.ForeignKeyConstraint(
            ["team_name"], ["team.name"], name="fk_station_state_team", onupdate="CASCADE"
        ),
        sa.CheckConstraint(
            "status IN ('idle', 'login', 'start', 'complete', 'review')",
            name="ck_station_state_status",
        ),
        sa.CheckConstraint(
            "(status = 'idle' AND team_name IS NULL) OR "
            "(status <> 'idle' AND team_name IS NOT NULL)",
            name="ck_station_state_team",
        ),
        sa.CheckConstraint(
            "(status = 'review' AND review_score IS NOT NULL AND review_score IN (0, 1, 2)) OR "
            "(status <> 'review' AND review_score IS NULL)",
            name="ck_station_state_review",
        ),
    )

    # The controller may already have created this table. Keep its rows and its
    # column names so the current db.py continues to work during the transition.
    # team_id is the resolved name (e.g. Team-01), not an NFC UUID or numeric FK.
    op.execute("""
        CREATE TABLE IF NOT EXISTS station_events (
            id SERIAL PRIMARY KEY,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            station_id VARCHAR(50) NOT NULL,
            team_id VARCHAR(50) NOT NULL,
            event_type VARCHAR(20) NOT NULL
        )
    """)
    op.execute("ALTER TABLE station_events ADD COLUMN IF NOT EXISTS review_score SMALLINT")
    # Grafana can filter by time, or look up a station's latest events quickly.
    op.execute("CREATE INDEX IF NOT EXISTS ix_station_events_created_at ON station_events (created_at)")
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_station_events_station_time
        ON station_events (station_id, created_at DESC, id DESC)
    """)


def downgrade() -> None:
    op.drop_table("station_state")
    op.drop_constraint("uq_team_name", "team", type_="unique")
    op.add_column("team", sa.Column("signature", sa.String(length=255), nullable=True))
    # Keep station_events and its indexes: it may predate this migration and the
    # old controller still writes to it. Removed signature values cannot return.
