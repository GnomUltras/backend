"""Keep results and events for every team round.

Revision ID: 0004_team_rounds
Revises: 0003_result_timing
"""

from alembic import op
import sqlalchemy as sa


revision = "0004_team_rounds"
down_revision = "0003_result_timing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing history belongs to round 1; later rounds get their own result rows.
    for table in ("results", "station_events"):
        op.add_column(table, sa.Column("round", sa.Integer(), nullable=False, server_default="1"))
        op.create_check_constraint(f"ck_{table}_round", table, '"round" >= 1')
    op.drop_constraint("pk_results", "results", type_="primary")
    op.create_primary_key("pk_results", "results", ["team_id", "round", "station_id"])
    op.create_index("ix_station_events_team_round", "station_events", ["team_id", "round"])

    # Remember the visit's round even if its last MQTT acknowledgement arrives late.
    op.add_column("station_state", sa.Column("round", sa.Integer(), nullable=True))
    op.execute('UPDATE station_state SET "round" = 1 WHERE status <> \'idle\'')
    op.create_check_constraint(
        "ck_station_state_round", "station_state",
        '(status = \'idle\' AND "round" IS NULL) OR '
        '(status <> \'idle\' AND "round" IS NOT NULL AND "round" >= 1)',
    )


def downgrade() -> None:
    # The old schema cannot preserve multiple rounds. Refuse to discard history.
    op.execute('''DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM results WHERE "round" > 1)
           OR EXISTS (SELECT 1 FROM station_events WHERE "round" > 1)
           OR EXISTS (SELECT 1 FROM station_state WHERE "round" > 1) THEN
            RAISE EXCEPTION 'Cannot downgrade while multiple rounds exist';
        END IF;
    END $$''')
    op.drop_constraint("ck_station_state_round", "station_state", type_="check")
    op.drop_column("station_state", "round")
    op.drop_index("ix_station_events_team_round", table_name="station_events")
    op.drop_constraint("pk_results", "results", type_="primary")
    op.create_primary_key("pk_results", "results", ["team_id", "station_id"])
    for table in ("results", "station_events"):
        op.drop_constraint(f"ck_{table}_round", table, type_="check")
        op.drop_column(table, "round")
