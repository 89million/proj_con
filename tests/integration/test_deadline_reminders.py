"""Integration tests for 24-hour deadline reminders."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest_asyncio

from app import state
from app.models import Book, BordaVote, Meetup, MeetupOption, Season, SeasonParticipant, SeasonState

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def submit_season_with_deadline(db, test_admin, test_user):
    """Submit-phase season with a deadline 20h away; only admin has submitted."""
    season = Season(
        name="Reminder Test",
        state=SeasonState.submit,
        page_limit=400,
        submit_deadline=datetime.utcnow() + timedelta(hours=20),
    )
    db.add(season)
    await db.commit()
    await db.refresh(season)
    db.add(SeasonParticipant(season_id=season.id, user_id=test_admin.id))
    db.add(SeasonParticipant(season_id=season.id, user_id=test_user.id))
    db.add(
        Book(
            title="Admin Book",
            author="Author A",
            page_count=200,
            submitter_id=test_admin.id,
            season_id=season.id,
        )
    )
    await db.commit()
    await db.refresh(season)
    return season


@pytest_asyncio.fixture
async def ranking_season_with_deadline(db, test_admin, test_user):
    """Ranking-phase season with a deadline 20h away; only admin has ranked."""
    season = Season(
        name="Ranking Reminder",
        state=SeasonState.ranking,
        page_limit=400,
        ranking_deadline=datetime.utcnow() + timedelta(hours=20),
    )
    db.add(season)
    await db.commit()
    await db.refresh(season)
    db.add(SeasonParticipant(season_id=season.id, user_id=test_admin.id))
    db.add(SeasonParticipant(season_id=season.id, user_id=test_user.id))
    book = Book(
        title="Book A",
        author="Auth",
        page_count=200,
        submitter_id=test_admin.id,
        season_id=season.id,
    )
    db.add(book)
    await db.flush()
    db.add(BordaVote(user_id=test_admin.id, season_id=season.id, book_id=book.id, rank=1))
    await db.commit()
    await db.refresh(season)
    return season


@pytest_asyncio.fixture
async def meetup_with_deadline(db, test_admin, test_user):
    """A meetup poll closing in 20h with one option; only admin has voted."""
    season = Season(name="Meetup Season", state=SeasonState.complete, page_limit=400)
    db.add(season)
    await db.flush()
    db.add(SeasonParticipant(season_id=season.id, user_id=test_admin.id))
    db.add(SeasonParticipant(season_id=season.id, user_id=test_user.id))
    meetup = Meetup(
        season_id=season.id,
        deadline=datetime.utcnow() + timedelta(hours=20),
    )
    db.add(meetup)
    await db.flush()
    option = MeetupOption(
        meetup_id=meetup.id,
        proposed_by=test_admin.id,
        event_datetime=datetime.utcnow() + timedelta(weeks=3),
        location="Monk",
    )
    db.add(option)
    await db.commit()
    await db.refresh(meetup)
    return meetup


# ---------------------------------------------------------------------------
# Submit reminder
# ---------------------------------------------------------------------------


async def test_submit_reminder_fires_within_24h(db, submit_season_with_deadline):
    """check_24h_reminders sends an email to non-submitters when deadline < 24h."""
    season = submit_season_with_deadline
    with patch("app.notify.notify_all", new_callable=AsyncMock) as mock_notify:
        await state.check_24h_reminders(db, season)
    mock_notify.assert_called_once()
    msg = mock_notify.call_args.kwargs.get("discord_msg", mock_notify.call_args.args[1])
    assert "submission" in msg.lower()


async def test_submit_reminder_not_sent_twice(db, submit_season_with_deadline):
    """Reminder is not re-sent if submit_reminder_sent is already True."""
    season = submit_season_with_deadline
    season.submit_reminder_sent = True
    await db.commit()
    with patch("app.notify.notify_all", new_callable=AsyncMock) as mock_notify:
        await state.check_24h_reminders(db, season)
    mock_notify.assert_not_called()


async def test_submit_reminder_not_fired_outside_window(db, test_admin, test_user):
    """No reminder if deadline is more than 24h away."""
    season = Season(
        name="Far Deadline",
        state=SeasonState.submit,
        page_limit=400,
        submit_deadline=datetime.utcnow() + timedelta(hours=48),
    )
    db.add(season)
    await db.commit()
    await db.refresh(season)
    db.add(SeasonParticipant(season_id=season.id, user_id=test_admin.id))
    await db.commit()
    with patch("app.notify.notify_all", new_callable=AsyncMock) as mock_notify:
        await state.check_24h_reminders(db, season)
    mock_notify.assert_not_called()


async def test_submit_reminder_not_fired_after_deadline(db, test_admin, test_user):
    """No reminder if deadline has already passed."""
    season = Season(
        name="Past Deadline",
        state=SeasonState.submit,
        page_limit=400,
        submit_deadline=datetime.utcnow() - timedelta(hours=1),
    )
    db.add(season)
    await db.commit()
    await db.refresh(season)
    db.add(SeasonParticipant(season_id=season.id, user_id=test_admin.id))
    await db.commit()
    with patch("app.notify.notify_all", new_callable=AsyncMock) as mock_notify:
        await state.check_24h_reminders(db, season)
    mock_notify.assert_not_called()


# ---------------------------------------------------------------------------
# Ranking reminder
# ---------------------------------------------------------------------------


async def test_ranking_reminder_fires_within_24h(db, ranking_season_with_deadline, test_user):
    """check_24h_reminders sends ranking reminder to non-rankers."""
    season = ranking_season_with_deadline
    with patch("app.notify.notify_all", new_callable=AsyncMock) as mock_notify:
        await state.check_24h_reminders(db, season)
    mock_notify.assert_called_once()
    msg = mock_notify.call_args.kwargs.get("discord_msg", mock_notify.call_args.args[1])
    assert "ranking" in msg.lower()


async def test_ranking_reminder_not_sent_twice(db, ranking_season_with_deadline):
    """Ranking reminder not re-sent once flag is set."""
    season = ranking_season_with_deadline
    season.ranking_reminder_sent = True
    await db.commit()
    with patch("app.notify.notify_all", new_callable=AsyncMock) as mock_notify:
        await state.check_24h_reminders(db, season)
    mock_notify.assert_not_called()


# ---------------------------------------------------------------------------
# Meetup reminder
# ---------------------------------------------------------------------------


async def test_meetup_reminder_fires_within_24h(db, meetup_with_deadline):
    """check_meetup_24h_reminder fires when poll closes within 24h."""
    meetup = meetup_with_deadline
    with patch("app.notify.notify_all", new_callable=AsyncMock) as mock_notify:
        await state.check_meetup_24h_reminder(db, meetup)
    mock_notify.assert_called_once()
    msg = mock_notify.call_args.kwargs.get("discord_msg", mock_notify.call_args.args[1])
    assert "meetup" in msg.lower() or "voting" in msg.lower()


async def test_meetup_reminder_not_sent_twice(db, meetup_with_deadline):
    """Meetup reminder not re-sent once flag is set."""
    meetup = meetup_with_deadline
    meetup.reminder_sent = True
    await db.commit()
    with patch("app.notify.notify_all", new_callable=AsyncMock) as mock_notify:
        await state.check_meetup_24h_reminder(db, meetup)
    mock_notify.assert_not_called()


async def test_meetup_reminder_not_fired_outside_window(db, test_admin, test_user):
    """No meetup reminder when deadline is more than 24h away."""
    season = Season(name="Far Meetup", state=SeasonState.complete, page_limit=400)
    db.add(season)
    await db.flush()
    db.add(SeasonParticipant(season_id=season.id, user_id=test_admin.id))
    meetup = Meetup(
        season_id=season.id,
        deadline=datetime.utcnow() + timedelta(hours=48),
    )
    db.add(meetup)
    await db.commit()
    await db.refresh(meetup)
    with patch("app.notify.notify_all", new_callable=AsyncMock) as mock_notify:
        await state.check_meetup_24h_reminder(db, meetup)
    mock_notify.assert_not_called()
