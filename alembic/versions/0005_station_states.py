"""Separate station states from MQTT transition names.

Revision ID: 0005_station_states
Revises: 0004_team_rounds
"""

from alembic import op

revision = "0005_station_states"
down_revision = "0004_team_rounds"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("ck_station_state_status", "station_state", type_="check")
    op.drop_constraint("ck_station_state_review", "station_state", type_="check")
    # Preserve occupancy, rounds, timestamps, and scores. A stored score marks
    # a review already accepted but still waiting for its nextStation handoff.
    op.execute("""UPDATE station_state SET status = CASE status
        WHEN 'login' THEN 'logged_in' WHEN 'start' THEN 'running'
        WHEN 'complete' THEN 'reviewing' WHEN 'review' THEN 'reviewing'
        ELSE status END""")
    op.create_check_constraint(
        "ck_station_state_status", "station_state",
        "status IN ('idle', 'logged_in', 'running', 'reviewing')",
    )
    op.create_check_constraint(
        "ck_station_state_review", "station_state",
        "review_score IS NULL OR (status = 'reviewing' AND review_score IN (0, 1, 2))",
    )


def downgrade():
    op.drop_constraint("ck_station_state_status", "station_state", type_="check")
    op.drop_constraint("ck_station_state_review", "station_state", type_="check")
    op.execute("""UPDATE station_state SET status = CASE status
        WHEN 'logged_in' THEN 'login' WHEN 'running' THEN 'start'
        WHEN 'reviewing' THEN CASE WHEN review_score IS NULL THEN 'complete' ELSE 'review' END
        ELSE status END""")
    op.create_check_constraint(
        "ck_station_state_status", "station_state",
        "status IN ('idle', 'login', 'start', 'complete', 'review')",
    )
    op.create_check_constraint(
        "ck_station_state_review", "station_state",
        "(status = 'review' AND review_score IS NOT NULL AND review_score IN (0, 1, 2)) OR "
        "(status <> 'review' AND review_score IS NULL)",
    )
