"""Remove review scores from live station state; retain review history.

Revision ID: 0010_remove_state_review
Revises: 0009_high_score
"""

from alembic import op
import sqlalchemy as sa

revision = "0010_remove_state_review"
down_revision = "0009_high_score"
branch_labels = None
depends_on = None


def upgrade():
    # Accepted reviews already exist in results and station_events. Their
    # records, including pending handoffs and zero scores, remain untouched.
    op.drop_constraint("ck_station_state_review", "station_state", type_="check")
    op.drop_column("station_state", "review_score")


def downgrade():
    op.add_column("station_state", sa.Column("review_score", sa.SmallInteger(), nullable=True))
    op.execute("""UPDATE station_state ss SET review_score = r.review::smallint
        FROM results r WHERE r.station_id = ss.station_id AND r.team_id = ss.team_id
          AND ss.status = 'reviewing' AND r.status = 'review' AND r.review IN ('0', '1', '2')""")
    op.create_check_constraint(
        "ck_station_state_review", "station_state",
        "review_score IS NULL OR (status = 'reviewing' AND review_score IN (0, 1, 2))",
    )
