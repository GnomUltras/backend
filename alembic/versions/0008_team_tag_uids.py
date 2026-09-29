"""Register the five physical team tags for new and existing databases.

Revision ID: 0008_team_tag_uids
Revises: 0007_station_names
"""

from alembic import op
import sqlalchemy as sa

revision = "0008_team_tag_uids"
down_revision = "0007_station_names"
branch_labels = None
depends_on = None

TEAM_TAGS = (
    ("Team-01", "74 FA CB 01"),
    ("Team-02", "35 7F CB 01"),
    ("Team-03", "2C A1 19 49"),
    ("Team-04", "63 12 46 16"),
    ("Team-05", "F3 05 59 16"),
)


def upgrade():
    connection = op.get_bind()
    for name, uid in TEAM_TAGS:
        # Game records reference team.name, so changing the tag preserves visits
        # and active assignments. A UID owned by another team fails atomically.
        connection.execute(sa.text(
            "INSERT INTO team (id, name) VALUES (:uid, :name) "
            "ON CONFLICT (name) DO UPDATE SET id = EXCLUDED.id"
        ), {"uid": uid, "name": name})


def downgrade():
    # Registration is real data. Keep the tags rather than restoring fake IDs
    # or deleting teams and their game history when reverting the revision.
    pass
