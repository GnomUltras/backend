"""Use team.id for scanned chips and team.name for game references.

Revision ID: 0006_team_identifiers
Revises: 0005_station_states
"""

from alembic import op
import sqlalchemy as sa

revision = "0006_team_identifiers"
down_revision = "0005_station_states"
branch_labels = None
depends_on = None


def upgrade():
    # Names are already unique (0002). Move game references to that unique key
    # before replacing the old team IDs with the known scanned chip IDs.
    op.drop_constraint("fk_results_team_id", "results", type_="foreignkey")
    op.drop_constraint("fk_station_state_team", "station_state", type_="foreignkey")
    for table in ("results", "station_state", "station_events"):
        op.alter_column(table, "team_id", type_=sa.String(255), existing_type=sa.String(50))
        op.execute(f"UPDATE {table} AS game SET team_id = team.name "
                   "FROM team WHERE game.team_id = team.id")

    connection = op.get_bind()
    for number in range(1, 6):
        name = f"Team-{number:02d}"
        # Seed the former config examples once; preserve existing display names.
        connection.execute(sa.text(
            "UPDATE team SET id = :chip_id WHERE id = :old_id"
        ), {"chip_id": f"AA BB CC {number:02d}", "old_id": name})
        connection.execute(sa.text(
            "INSERT INTO team (id, name) VALUES (:chip_id, :name) "
            "ON CONFLICT DO NOTHING"
        ), {"chip_id": f"AA BB CC {number:02d}", "name": name})

    op.create_foreign_key("fk_results_team_id", "results", "team", ["team_id"], ["name"],
                          onupdate="CASCADE", ondelete="CASCADE")
    op.create_foreign_key("fk_station_state_team", "station_state", "team", ["team_id"], ["name"],
                          onupdate="CASCADE")
    # Event team names remain historical snapshots, without a foreign key.
    # team.id remains its unique, non-null string primary key; no extra column.


def downgrade():
    op.drop_constraint("fk_results_team_id", "results", type_="foreignkey")
    op.drop_constraint("fk_station_state_team", "station_state", type_="foreignkey")
    for table in ("results", "station_state", "station_events"):
        op.execute(f"UPDATE {table} AS game SET team_id = team.id "
                   "FROM team WHERE game.team_id = team.name")
        # Historical events can refer to renamed/deleted teams. Never truncate
        # their names silently when returning to the older 50-character schema.
        connection = op.get_bind()
        if connection.execute(sa.text(
            f"SELECT 1 FROM {table} WHERE length(team_id) > 50 LIMIT 1"
        )).first():
            raise ValueError(f"Cannot downgrade: {table} contains team names longer than 50 characters.")
        op.alter_column(table, "team_id", type_=sa.String(50), existing_type=sa.String(255))
    op.create_foreign_key("fk_results_team_id", "results", "team", ["team_id"], ["id"],
                          ondelete="CASCADE")
    op.create_foreign_key("fk_station_state_team", "station_state", "team", ["team_id"], ["id"],
                          onupdate="CASCADE")
    # Keep chip IDs and team rows; reverting the schema must not discard them.
