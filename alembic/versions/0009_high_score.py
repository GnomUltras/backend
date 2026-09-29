"""Keep resettable live progress and persistent duration highscores.

Revision ID: 0009_high_score
Revises: 0008_team_tag_uids
"""

from alembic import op
import sqlalchemy as sa

revision = "0009_high_score"
down_revision = "0008_team_tag_uids"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "high_score",
        sa.Column("station_id", sa.String(50), primary_key=True),
        sa.Column("team_name", sa.String(255), nullable=True),
        sa.Column("time", sa.Interval(), nullable=True),
        sa.ForeignKeyConstraint(["station_id"], ["station.station_id"],
                                name="fk_high_score_station_id", ondelete="CASCADE"),
        sa.CheckConstraint(
            "(team_name IS NULL AND time IS NULL) OR "
            "(team_name IS NOT NULL AND time IS NOT NULL AND time >= INTERVAL '0 seconds')",
            name="ck_high_score_duration",
        ),
    )
    # Preserve the fastest existing result before older live-result rows go away.
    op.execute("""INSERT INTO high_score (station_id, team_name, time)
        SELECT DISTINCT ON (station_id) station_id, team_id, completed_at - started_at
        FROM results WHERE started_at IS NOT NULL AND completed_at IS NOT NULL
        ORDER BY station_id, completed_at - started_at, completed_at, team_id""")
    op.execute("""INSERT INTO high_score (station_id)
        SELECT station_id FROM station ON CONFLICT (station_id) DO NOTHING""")

    # Mark already finished games so their tags can start again. An assigned
    # station means a handoff is still pending: leave that game for the controller.
    op.execute("""INSERT INTO station_events (station_id, team_id, event_type, "round")
        SELECT MIN(r.station_id), r.team_id, 'round_complete', r."round"
        FROM results r JOIN station s ON s.station_id = r.station_id
        WHERE r.status = 'review' AND r.completed_at IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM station_state ss
                          WHERE ss.team_id = r.team_id AND ss."round" = r."round")
          AND NOT EXISTS (SELECT 1 FROM station_events e WHERE e.team_id = r.team_id
                          AND e."round" = r."round" AND e.event_type = 'round_complete')
        GROUP BY r.team_id, r."round"
        HAVING COUNT(DISTINCT r.station_id) = (SELECT COUNT(*) FROM station)""")
    # Only the latest unfinished game belongs in results. Historical events
    # are never deleted or renumbered; highscores above include all old results.
    op.execute("""DELETE FROM results r
        WHERE r."round" < (SELECT MAX(newer."round") FROM results newer WHERE newer.team_id = r.team_id)
           OR EXISTS (SELECT 1 FROM station_events e WHERE e.team_id = r.team_id
                      AND e."round" = r."round" AND e.event_type = 'round_complete')""")
    op.drop_constraint("pk_results", "results", type_="primary")
    op.drop_constraint("ck_results_round", "results", type_="check")
    op.drop_column("results", "round")
    op.create_primary_key("pk_results", "results", ["team_id", "station_id"])
    op.drop_constraint("ck_station_state_round", "station_state", type_="check")
    op.drop_column("station_state", "round")


def downgrade() -> None:
    # Restore numbering for current progress. Cleared results remain represented
    # by event history; downgrading cannot recreate every historical result row.
    op.add_column("results", sa.Column("round", sa.Integer(), nullable=False, server_default="1"))
    op.execute("""UPDATE results r SET "round" = COALESCE(
        (SELECT MAX(e."round") FROM station_events e WHERE e.team_id = r.team_id), 1)""")
    op.drop_constraint("pk_results", "results", type_="primary")
    op.create_primary_key("pk_results", "results", ["team_id", "round", "station_id"])
    op.create_check_constraint("ck_results_round", "results", '"round" >= 1')
    op.add_column("station_state", sa.Column("round", sa.Integer(), nullable=True))
    op.execute("""UPDATE station_state ss SET "round" = COALESCE(
        (SELECT MAX(e."round") FROM station_events e WHERE e.team_id = ss.team_id), 1)
        WHERE ss.status <> 'idle'""")
    op.create_check_constraint("ck_station_state_round", "station_state",
        '(status = \'idle\' AND "round" IS NULL) OR '
        '(status <> \'idle\' AND "round" IS NOT NULL AND "round" >= 1)')
    op.drop_table("high_score")
