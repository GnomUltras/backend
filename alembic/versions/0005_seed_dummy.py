"""seed dummy data for station_events

Revision ID: 0002_seed_dummy
Revises: <PUT_YOUR_PREVIOUS_REVISION_ID_HERE>
Create Date: 2026-09-28

Adds the review_score column (if missing) and inserts demo events so the
Grafana dashboard has something to show.

Demo rows are all timestamped on 2025-01-01 (UTC) so that downgrade() can
remove exactly those rows and nothing else.

Resulting dashboard state:
  station_1 free, station_2 occupied (team_1), station_3 occupied (team_3),
  station_4 free, station_5 pending (team_3), station_6 free
"""
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0005_seed_dummy"
down_revision = "0004_team_rounds"
branch_labels = None
depends_on = None

BASE = datetime(2025, 1, 1, 8, 0, 0, tzinfo=timezone.utc)
GAP = timedelta(minutes=2)

# Per station, in chronological order:
# (team, repair duration in seconds, event after repair, review_score)
# A duration of None means the repair is still running (no end event).
REPAIRS = {
    "station_1": [
        ("team_3", 700, "free", 4),
        ("team_2", 640, "free", 4),
        ("team_5", 660, "free", 3),
        ("team_1", 623, "free", 5),   # fastest: 10:23
    ],
    "station_2": [
        ("team_1", 506, "free", 3),   # fastest: 08:26
        ("team_1", None, None, None),  # currently occupied
    ],
    "station_3": [
        ("team_5", 405, "free", 3),   # fastest: 06:45
        ("team_2", 440, "free", 2),
        ("team_3", None, None, None),  # currently occupied
    ],
    "station_4": [
        ("team_1", 703, "free", 4),
        ("team_2", 475, "free", 5),   # fastest: 07:55
    ],
    "station_5": [
        ("team_5", 724, "free", 3),
        ("team_3", 542, "pending", 2),  # fastest: 09:02, awaiting inspection
    ],
    "station_6": [
        ("team_3", 481, "free", 4),
        ("team_4", 300, "free", 5),   # fastest: 05:00
    ],
}


def _build_rows():
    rows = []
    for idx, (station, repairs) in enumerate(REPAIRS.items()):
        t = BASE + timedelta(minutes=idx)  # stagger stations slightly
        for team, secs, end_event, review in repairs:
            rows.append(
                dict(ts=t, station=station, team=team, event="occupied", review=None)
            )
            if secs is None:
                break
            t = t + timedelta(seconds=secs)
            rows.append(
                dict(ts=t, station=station, team=team, event=end_event, review=review)
            )
            t = t + GAP
    return rows


def upgrade() -> None:
    op.execute(
        "ALTER TABLE station_events ADD COLUMN IF NOT EXISTS review_score SMALLINT"
    )
    op.get_bind().execute(
        sa.text(
            """
            INSERT INTO station_events
                (created_at, station_id, team_id, event_type, review_score)
            VALUES (:ts, :station, :team, :event, :review)
            """
        ),
        _build_rows(),
    )


def downgrade() -> None:
    # Remove only the demo rows (all created on 2025-01-01 UTC)
    op.execute(
        """
        DELETE FROM station_events
        WHERE created_at >= '2025-01-01 00:00:00+00'
          AND created_at <  '2025-01-02 00:00:00+00'
        """
    )
    # review_score column is intentionally kept
