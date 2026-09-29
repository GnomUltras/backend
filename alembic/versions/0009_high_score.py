from alembic import op
import sqlalchemy as sa

revision = "0009_high_score"
down_revision = "0008_team_tag_uids"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        "high_score",
        sa.Column("station_id", sa.String(length = 50), primary_key=True),
        sa.Column("team_name", sa.String(length = 150)),
        sa.Column("time", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
                    ["station_id"], ["station.station_id"], name="fk_high_score_station_id", ondelete="CASCADE"
                ),
    )
    op.drop_column('results', 'round')
    op.drop_column('station_state', 'round')

def downgrade() -> None:
    op.drop_table("high_score")
    op.add_column('results', sa.Column("round", sa.Integer(), nullable=False, server_default="1"))
    op.add_column('station_state', sa.Column("round", sa.Integer(), nullable=False, server_default="1"))