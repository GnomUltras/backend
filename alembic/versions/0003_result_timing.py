"""Give result timestamps explicit names and validate their order.

Revision ID: 0003_result_timing
Revises: 0002_station_state
"""

from alembic import op


revision = "0003_result_timing"
down_revision = "0002_station_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Rename the existing timezone-aware columns without losing recorded times.
    # Timing covers accepted start -> complete, excluding login and review.
    op.alter_column("results", "start_time", new_column_name="started_at")
    op.alter_column("results", "end_time", new_column_name="completed_at")
    op.create_check_constraint(
        "ck_results_timing",
        "results",
        "completed_at IS NULL OR "
        "(started_at IS NOT NULL AND completed_at >= started_at)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_results_timing", "results", type_="check")
    op.alter_column("results", "completed_at", new_column_name="end_time")
    op.alter_column("results", "started_at", new_column_name="start_time")
