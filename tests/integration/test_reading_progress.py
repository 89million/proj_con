"""Integration tests for reading-progress check-ins on the complete page."""

import pytest_asyncio
from sqlalchemy import func as sa_func
from sqlalchemy import select

from app.models import Book, BracketMatchup, ReadingProgress, Season, SeasonParticipant, SeasonState

from .conftest import make_client


@pytest_asyncio.fixture
async def complete_season(db, test_admin, test_user):
    """A completed season with both users as participants and a decided winner."""
    season = Season(name="Read Season", state=SeasonState.complete, page_limit=400)
    db.add(season)
    await db.flush()

    db.add(SeasonParticipant(season_id=season.id, user_id=test_admin.id))
    db.add(SeasonParticipant(season_id=season.id, user_id=test_user.id))

    book1 = Book(
        title="Winning Book",
        author="Author A",
        page_count=300,
        submitter_id=test_admin.id,
        season_id=season.id,
    )
    book2 = Book(
        title="Losing Book",
        author="Author B",
        page_count=250,
        submitter_id=test_user.id,
        season_id=season.id,
    )
    db.add_all([book1, book2])
    await db.flush()
    db.add(
        BracketMatchup(
            season_id=season.id,
            round=1,
            position=1,
            book_a_id=book1.id,
            book_b_id=book2.id,
            winner_id=book1.id,
        )
    )
    await db.commit()
    await db.refresh(season)
    return season


async def test_progress_check_in_creates_row(engine, db, test_user, complete_season):
    """POST /reading-progress stores the user's percent and returns to /complete."""
    async with make_client(engine, test_user) as client:
        resp = await client.post("/reading-progress", data={"percent": "45"})
    assert resp.status_code == 302
    assert resp.headers["location"] == "/complete#progress"

    result = await db.execute(
        select(ReadingProgress).where(
            ReadingProgress.season_id == complete_season.id,
            ReadingProgress.user_id == test_user.id,
        )
    )
    progress = result.scalar_one()
    assert progress.percent == 45


async def test_progress_update_overwrites_previous(engine, db, test_user, complete_season):
    """Checking in twice updates the existing row (upsert)."""
    async with make_client(engine, test_user) as client:
        await client.post("/reading-progress", data={"percent": "20"})
        await client.post("/reading-progress", data={"percent": "60"})

    count = await db.scalar(
        select(sa_func.count()).where(ReadingProgress.season_id == complete_season.id)
    )
    assert count == 1

    result = await db.execute(
        select(ReadingProgress).where(ReadingProgress.user_id == test_user.id)
    )
    assert result.scalar_one().percent == 60


async def test_progress_percent_is_clamped(engine, db, test_user, complete_season):
    """Out-of-range percents are clamped to 0–100."""
    async with make_client(engine, test_user) as client:
        await client.post("/reading-progress", data={"percent": "150"})
    result = await db.execute(
        select(ReadingProgress).where(ReadingProgress.user_id == test_user.id)
    )
    assert result.scalar_one().percent == 100

    async with make_client(engine, test_user) as client:
        await client.post("/reading-progress", data={"percent": "-10"})
    await db.commit()  # refresh session state
    result = await db.execute(
        select(ReadingProgress).where(ReadingProgress.user_id == test_user.id)
    )
    assert result.scalar_one().percent == 0


async def test_progress_ignored_without_complete_season(engine, db, test_user):
    """With no completed season the post is a harmless redirect."""
    async with make_client(engine, test_user) as client:
        resp = await client.post("/reading-progress", data={"percent": "50"})
    assert resp.status_code == 302

    count = await db.scalar(select(sa_func.count()).select_from(ReadingProgress))
    assert count == 0


async def test_complete_page_shows_progress_section(engine, test_user, complete_season):
    """The /complete page renders the check-in form and the whole club's bars."""
    async with make_client(engine, test_user) as client:
        resp = await client.get("/complete")
    assert resp.status_code == 200
    assert "How's the reading going?" in resp.text
    assert 'action="/reading-progress"' in resp.text


async def test_participants_show_at_zero_before_checking_in(
    engine, db, test_user, test_admin, complete_season
):
    """Every season participant appears on the board even before checking in."""
    async with make_client(engine, test_user) as client:
        resp = await client.get("/complete")
    assert resp.text.count("0%") >= 2


async def test_progress_board_sorted_by_percent(engine, db, test_user, test_admin, complete_season):
    """Members who are further along appear first (leaderboard order)."""
    db.add(ReadingProgress(season_id=complete_season.id, user_id=test_user.id, percent=80))
    db.add(ReadingProgress(season_id=complete_season.id, user_id=test_admin.id, percent=20))
    await db.commit()

    async with make_client(engine, test_user) as client:
        resp = await client.get("/complete")
    assert resp.status_code == 200
    # The 80% bar must be rendered before the 20% bar
    assert "width: 80%" in resp.text and "width: 20%" in resp.text
    assert resp.text.index("width: 80%") < resp.text.index("width: 20%")


async def test_finished_shows_celebration(engine, db, test_user, complete_season):
    """100% renders as Finished with a celebration emoji."""
    async with make_client(engine, test_user) as client:
        await client.post("/reading-progress", data={"percent": "100"})
    async with make_client(engine, test_user) as client:
        resp = await client.get("/complete")
    assert "Finished 🎉" in resp.text
