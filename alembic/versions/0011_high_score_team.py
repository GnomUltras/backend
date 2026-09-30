from alembic import op
import sqlalchemy as sa

revision = "0011_high_score_team"
down_revision = "0010_remove_state_review"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        "high_score_team",
        sa.Column("team_name", sa.String(50), primary_key=True),
        sa.Column("time", sa.Interval(), nullable=True),
        sa.Column("round", sa.Integer(), primary_key=True),
    )

def downgrade() -> None:
    op.drop_table("high_score_team")
