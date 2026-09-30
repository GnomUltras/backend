"""Validate team game durations and backfill retained completed games.

Revision ID: 0012_team_score_constraints
Revises: 0011_high_score_team
"""

from alembic import op
import sqlalchemy as sa

revision = "0012_team_score_constraints"
down_revision = "0011_high_score_team"
branch_labels = None
depends_on = None


def upgrade():
    # Team names elsewhere allow 255 characters. Scores retain historical names
    # instead of cascading away if a team is later renamed or removed.
    op.alter_column("high_score_team", "team_name", type_=sa.String(255), existing_type=sa.String(50))
    op.alter_column("high_score_team", "time", nullable=False, existing_type=sa.Interval())
    op.create_check_constraint("ck_high_score_team_round", "high_score_team", '"round" >= 1')
    op.create_check_constraint("ck_high_score_team_time", "high_score_team", "time >= INTERVAL '0 seconds'")
    op.create_index("ix_high_score_team_time", "high_score_team", ["time"])

    # Only backfill completed games whose full results still exist. Cleared
    # earlier games cannot be reconstructed reliably from the live result table.
    op.execute('''INSERT INTO high_score_team (team_name, "round", time)
        SELECT r.team_id, e."round", SUM(r.completed_at - r.started_at)
        FROM results r JOIN station s ON s.station_id = r.station_id
        JOIN LATERAL (
            SELECT event_type, "round" FROM station_events
            WHERE team_id = r.team_id ORDER BY "round" DESC, id DESC LIMIT 1
        ) e ON e.event_type = 'round_complete'
        GROUP BY r.team_id, e."round"
        HAVING COUNT(*) = (SELECT COUNT(*) FROM station)
           AND BOOL_AND(r.status = 'review' AND r.started_at IS NOT NULL
                        AND r.completed_at IS NOT NULL AND r.completed_at >= r.started_at)
        ON CONFLICT (team_name, "round") DO NOTHING''')


def downgrade():
    op.drop_index("ix_high_score_team_time", table_name="high_score_team")
    op.drop_constraint("ck_high_score_team_time", "high_score_team", type_="check")
    op.drop_constraint("ck_high_score_team_round", "high_score_team", type_="check")
    op.alter_column("high_score_team", "time", nullable=True, existing_type=sa.Interval())
    # Keep the wider name column so downgrade cannot truncate saved team names.
