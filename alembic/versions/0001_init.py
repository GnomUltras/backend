"""init schema: team, station, results

Revision ID: 0001_init
Revises:
Create Date: 2026-09-23

Derived from Untitled_Diagram.drawio:
  - team(id PK, signature, name)
  - station(station_id PK, name)
  - results(team_id FK->team.id, station_id FK->station.station_id,
            start_time, end_time, review)  -- composite PK (team_id, station_id)

Team IDs are strings such as Team-01; station IDs are strings such as station01.

Relationships:
  team (1) --- (n) results
  station (1) --- (n) results
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0001_init"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "team",
        sa.Column("id", sa.String(length=50), primary_key=True),
        sa.Column("signature", sa.String(length=255), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
    )

    op.create_table(
        "station",
        sa.Column("station_id", sa.String(length=50), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
    )

    op.create_table(
        "results",
        sa.Column("team_id", sa.String(length=50), nullable=False),
        sa.Column("station_id", sa.String(length=50), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=True),
        sa.PrimaryKeyConstraint("team_id", "station_id", name="pk_results"),
        sa.ForeignKeyConstraint(
            ["team_id"], ["team.id"], name="fk_results_team_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["station_id"],
            ["station.station_id"],
            name="fk_results_station_id",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_results_team_id", "results", ["team_id"])
    op.create_index("ix_results_station_id", "results", ["station_id"])


def downgrade() -> None:
    op.drop_index("ix_results_station_id", table_name="results")
    op.drop_index("ix_results_team_id", table_name="results")
    op.drop_table("results")
    op.drop_table("station")
    op.drop_table("team")
