"""Integration tests for phase deadlines and auto-advance."""

from datetime import datetime, timedelta

import pytest_asyncio

from app import state
from app.models import Book, BordaVote, Season, SeasonParticipant, SeasonState


@pytest_asyncio.fixture
async def submit_season_past_deadline(db, test_admin, test_user):
    """A season in submit state with deadline in the past and one submission."""
    season = Season(
        name="Deadline Test",
        state=SeasonState.submit,
        page_limit=400,
        submit_deadline=datetime.utcnow() - timedelta(hours=1),
        ranking_deadline=datetime.utcnow() + timedelta(days=5),
    )
    db.add(season)
    await db.commit()
    await db.refresh(season)

    db.add(SeasonParticipant(season_id=season.id, user_id=test_admin.id))
    db.add(SeasonParticipant(season_id=season.id, user_id=test_user.id))

    # Only admin submits — test_user hasn't submitted but deadline has passed
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


async def test_deadline_auto_advance_submit(submit_season_past_deadline, db):
    """When submit deadline has passed, check_deadline_and_advance force-advances."""
    season = submit_season_past_deadline
    assert season.state == SeasonState.submit

    result = await state.check_deadline_and_advance(db, season)
    assert result is True
    await db.refresh(season)
    assert season.state == SeasonState.ranking


async def test_deadline_no_advance_before_deadline(db, test_admin, test_user):
    """A future deadline does not trigger auto-advance."""
    season = Season(
        name="Future Deadline",
        state=SeasonState.submit,
        page_limit=400,
        submit_deadline=datetime.utcnow() + timedelta(days=3),
    )
    db.add(season)
    await db.commit()
    await db.refresh(season)

    db.add(SeasonParticipant(season_id=season.id, user_id=test_admin.id))
    db.add(SeasonParticipant(season_id=season.id, user_id=test_user.id))
    await db.commit()

    result = await state.check_deadline_and_advance(db, season)
    assert result is False
    await db.refresh(season)
    assert season.state == SeasonState.submit


async def test_deadline_ranking_auto_advance(db, test_admin, test_user):
    """When ranking deadline passes, season force-advances even if not all ranked."""
    season = Season(
        name="Ranking Deadline",
        state=SeasonState.submit,
        page_limit=400,
        ranking_deadline=datetime.utcnow() - timedelta(hours=1),
    )
    db.add(season)
    await db.commit()
    await db.refresh(season)

    db.add(SeasonParticipant(season_id=season.id, user_id=test_admin.id))
    db.add(SeasonParticipant(season_id=season.id, user_id=test_user.id))

    # Add 2 books
    books = []
    for title, user in [("Book A", test_admin), ("Book B", test_user)]:
        b = Book(
            title=title,
            author="Auth",
            page_count=200,
            submitter_id=user.id,
            season_id=season.id,
        )
        db.add(b)
        books.append(b)
    await db.flush()

    # Move to ranking
    season.state = SeasonState.ranking
    await db.commit()

    # Only admin ranks — test_user hasn't ranked but deadline passed
    for rank, book in enumerate(books, start=1):
        db.add(BordaVote(user_id=test_admin.id, season_id=season.id, book_id=book.id, rank=rank))
    await db.commit()

    result = await state.check_deadline_and_advance(db, season)
    assert result is True
    await db.refresh(season)
    assert season.state == SeasonState.bracket
