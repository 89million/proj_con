"""Meetup scheduling defaults and the naive-UTC ↔ club-local boundary."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app import clock
from app.config import settings
from app.state import _next_weekday_at, plan_meetup_schedule


@pytest.fixture(autouse=True)
def club_defaults(monkeypatch):
    """Pin the settings the planner reads so the tests don't drift with config."""
    monkeypatch.setattr(settings, "club_timezone", "America/Los_Angeles")
    monkeypatch.setattr(settings, "meetup_reading_weeks", 4)
    monkeypatch.setattr(settings, "meetup_poll_days", 7)
    monkeypatch.setattr(settings, "meetup_min_buffer_days", 3)
    monkeypatch.setattr(settings, "meetup_date_options", 3)
    monkeypatch.setattr(settings, "meetup_default_day", "friday")
    monkeypatch.setattr(settings, "meetup_default_time", "19:00")


# ---------------------------------------------------------------------------
# The clock boundary
# ---------------------------------------------------------------------------


def test_to_local_shifts_by_club_offset():
    """Naive UTC in, club wall-clock out. 02:00 UTC is 7pm the previous day (PDT)."""
    assert clock.to_local(datetime(2026, 8, 15, 2, 0)).strftime("%Y-%m-%d %H:%M") == (
        "2026-08-14 19:00"
    )


def test_to_utc_round_trips():
    local = datetime(2026, 8, 14, 19, 0)
    assert clock.to_local(clock.to_utc(local)).replace(tzinfo=None) == local


def test_to_utc_handles_dst_boundary():
    """7pm is 7pm on both sides of the DST change, at different UTC offsets."""
    summer = clock.to_utc(datetime(2026, 7, 10, 19, 0))  # PDT, UTC-7
    winter = clock.to_utc(datetime(2026, 12, 11, 19, 0))  # PST, UTC-8
    assert summer.hour == 2  # next day 02:00Z
    assert winter.hour == 3  # next day 03:00Z


def test_utc_iso_marks_the_zone():
    """The Z is what stops browsers reading the countdown as local time."""
    stamped = clock.utc_iso(datetime(2026, 8, 15, 2, 0))
    assert stamped.endswith("Z")
    # Parsed back the way a browser would, it's the same instant.
    assert datetime.fromisoformat(stamped.replace("Z", "+00:00")) == datetime(
        2026, 8, 15, 2, 0, tzinfo=timezone.utc
    )


def test_format_local_tz_names_the_zone():
    assert clock.format_local_tz(datetime(2026, 8, 15, 2, 0)).endswith("PDT")


# ---------------------------------------------------------------------------
# _next_weekday_at
# ---------------------------------------------------------------------------


def test_next_weekday_at_finds_upcoming_friday():
    # 2026-08-12 is a Wednesday.
    assert _next_weekday_at(datetime(2026, 8, 12, 9, 0), "friday", "19:00") == datetime(
        2026, 8, 14, 19, 0
    )


def test_next_weekday_at_same_day_before_the_hour_stays_today():
    # Friday 9am, looking for Friday 7pm — that's today, not next week.
    assert _next_weekday_at(datetime(2026, 8, 14, 9, 0), "friday", "19:00") == datetime(
        2026, 8, 14, 19, 0
    )


def test_next_weekday_at_same_day_after_the_hour_rolls_forward():
    assert _next_weekday_at(datetime(2026, 8, 14, 20, 0), "friday", "19:00") == datetime(
        2026, 8, 21, 19, 0
    )


# ---------------------------------------------------------------------------
# plan_meetup_schedule — the actual complaint
# ---------------------------------------------------------------------------


def _local(dt):
    return clock.to_local(dt).replace(tzinfo=None)


@pytest.mark.parametrize("day_offset", range(7))
def test_gap_is_never_short_regardless_of_start_day(day_offset):
    """The old defaults gave 1–7 days depending on the weekday. Now it's ~3 weeks.

    This is the regression the whole change exists for, so it runs from every
    starting weekday rather than a convenient one.
    """
    now = datetime(2026, 8, 10, 17, 0) + timedelta(days=day_offset)
    deadline, candidates = plan_meetup_schedule(now)
    gap = min(candidates) - deadline
    assert gap >= timedelta(days=14), f"only {gap.days}d between poll close and meetup"


def test_poll_closes_a_week_out_and_meetup_is_a_month_out():
    now = datetime(2026, 8, 12, 17, 0)  # Wed 10am Pacific
    deadline, candidates = plan_meetup_schedule(now)

    assert (deadline - now).days == 7
    # First candidate is the first Friday at least 4 weeks out.
    assert (min(candidates) - now) >= timedelta(weeks=4)
    assert _local(min(candidates)).weekday() == 4


def test_seeds_distinct_weekly_dates():
    """Options must differ by date — the old code reused one datetime for every
    location, so the poll offered no choice of *when* at all."""
    _, candidates = plan_meetup_schedule(datetime(2026, 8, 12, 17, 0))
    assert len(candidates) == 3
    assert len(set(candidates)) == 3
    assert candidates[1] - candidates[0] == timedelta(days=7)
    assert candidates[2] - candidates[1] == timedelta(days=7)


def test_all_candidates_are_at_the_configured_local_hour():
    _, candidates = plan_meetup_schedule(datetime(2026, 8, 12, 17, 0))
    for c in candidates:
        assert _local(c).strftime("%H:%M") == "19:00"


def test_buffer_backstop_clamps_an_over_long_poll(monkeypatch):
    """Even with a poll longer than the reading window, the deadline stays clear
    of the first date by meetup_min_buffer_days."""
    monkeypatch.setattr(settings, "meetup_poll_days", 90)
    deadline, candidates = plan_meetup_schedule(datetime(2026, 8, 12, 17, 0))
    assert min(candidates) - deadline == timedelta(days=3)


def test_dates_survive_a_dst_transition(monkeypatch):
    """Seeded across the November change, every option is still local 7pm."""
    monkeypatch.setattr(settings, "meetup_date_options", 4)
    # Late-September start puts the four candidates either side of Nov 1 2026,
    # when Pacific goes from UTC-7 to UTC-8.
    _, candidates = plan_meetup_schedule(datetime(2026, 9, 25, 17, 0))
    hours = {_local(c).strftime("%H:%M") for c in candidates}
    assert hours == {"19:00"}
    # And they really are at two different UTC offsets.
    offsets = {
        c.replace(tzinfo=timezone.utc).astimezone(ZoneInfo("America/Los_Angeles")).utcoffset()
        for c in candidates
    }
    assert len(offsets) == 2
