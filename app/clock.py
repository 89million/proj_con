"""The one place naive UTC turns into club-local wall-clock, and back.

Every datetime in the database is naive UTC — whatever `datetime.utcnow()`
handed over. Every datetime a member reads is club-local. Mixing those two up
is what made the meetup countdown disagree with the meetup banner, which in
turn disagreed with the reminder emails, so all three now go through here.

Note the deliberate exception: columns filled by `server_default=func.now()`
(`created_at`, `shown_at`) are *not* naive UTC — under Postgres they hold the
database session's local wall-clock. Those are ordering keys, never shown to
anyone, so they stay out of this module. See `crud.recent_ad_impression_exists`
for the full story on that divergence.
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.config import settings


def club_tz() -> ZoneInfo:
    """The club's wall-clock timezone. Falls back to UTC if misconfigured."""
    try:
        return ZoneInfo(settings.club_timezone)
    except Exception:
        return ZoneInfo("UTC")


def to_local(dt: datetime) -> datetime:
    """Naive UTC → aware club-local."""
    return dt.replace(tzinfo=timezone.utc).astimezone(club_tz())


def to_utc(local_dt: datetime) -> datetime:
    """Naive club-local → naive UTC, for storage.

    DST-ambiguous times (the hour that repeats each autumn) resolve to the
    first occurrence, which is what `fold=0` means and what a member picking
    "1:30am" off a date field almost certainly intends.
    """
    return local_dt.replace(tzinfo=club_tz(), fold=0).astimezone(timezone.utc).replace(tzinfo=None)


def format_local(dt: datetime, fmt: str = "%A, %b %d at %-I:%M %p") -> str:
    """Naive UTC → a string in club-local time, with no timezone marker."""
    return to_local(dt).strftime(fmt)


def format_local_tz(dt: datetime, fmt: str = "%a %b %d at %-I:%M %p") -> str:
    """Same, with the zone abbreviation appended — for emails and Discord.

    Members read those away from the site, with no countdown next to them to
    disambiguate, so the zone has to be on the face of it.
    """
    local = to_local(dt)
    return f"{local.strftime(fmt)} {local.strftime('%Z')}"


def utc_iso(dt: datetime) -> str:
    """Naive UTC → an ISO string JavaScript reads as UTC.

    The `Z` is the entire point. `new Date("2026-08-29T14:00:00")` is parsed as
    *local* time by every browser, so handing the countdown a bare isoformat()
    shifted it by the viewer's offset.
    """
    return dt.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def local_now() -> datetime:
    """Current time as naive club-local wall-clock, for date arithmetic."""
    return to_local(datetime.utcnow()).replace(tzinfo=None)
