"""Add meetups.event_reminder_sent and meetups.stalled_notice_sent.

The existing reminder flags both track the scheduling *poll* closing.
event_reminder_sent tracks the 24h-before-the-meetup reminder, and
stalled_notice_sent keeps the "poll expired with nothing to finalize"
warning from being sent on every background check.

Revision ID: 0026
Revises: 0025
"""

import sqlalchemy as sa
from alembic import op

from app.config import settings

revision = "0026"
down_revision = "0025"


def _shift_event_datetimes(to_utc: bool) -> None:
    """Reinterpret meetup_options.event_datetime as club-local, storing UTC.

    Existing rows hold local wall-clock in a column the app now reads as UTC.
    Both the seeder (`hour=19` meaning 7pm) and the propose form (the member's
    own picked time) wrote them that way, so without this shift every meetup on
    record would suddenly render seven hours early.

    meetups.deadline is deliberately left alone — it was always written as
    `datetime.utcnow() + delta`, so it is genuinely UTC already. Only its
    *display* was wrong, and that is fixed in the templates.

    Postgres-only: SQLite has no timezone database to convert against, and the
    test suite builds its schema from the models rather than from migrations.
    """
    if op.get_bind().dialect.name != "postgresql":
        return
    tz = settings.club_timezone
    if to_utc:
        expr = f"(event_datetime AT TIME ZONE '{tz}') AT TIME ZONE 'UTC'"
    else:
        expr = f"(event_datetime AT TIME ZONE 'UTC') AT TIME ZONE '{tz}'"
    op.execute(f"UPDATE meetup_options SET event_datetime = {expr}")


def upgrade():
    op.add_column(
        "meetups",
        sa.Column("event_reminder_sent", sa.Boolean(), server_default="0", nullable=False),
    )
    op.add_column(
        "meetups",
        sa.Column("stalled_notice_sent", sa.Boolean(), server_default="0", nullable=False),
    )
    _shift_event_datetimes(to_utc=True)


def downgrade():
    _shift_event_datetimes(to_utc=False)
    op.drop_column("meetups", "stalled_notice_sent")
    op.drop_column("meetups", "event_reminder_sent")
