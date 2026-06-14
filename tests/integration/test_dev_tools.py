"""Integration tests for the dev-only simulation routes (auto-submit / auto-rank).

These are gated behind settings.dev_tools_enabled and must be no-ops when off.
"""

import pytest_asyncio
from sqlalchemy import select

from app import crud
from app.config import settings
from app.models import Book, Season, SeasonParticipant, SeasonState


async def _book_count(db, season_id: int) -> int:
    result = await db.execute(select(Book).where(Book.season_id == season_id))
    return len(result.scalars().all())


@pytest_asyncio.fixture
async def submit_season(db, test_admin, test_user):
    """A season in submit with the realistic default 400-page limit — many sample
    books exceed this, so auto-submit must still place a fitting book per user."""
    season = Season(name="Submit Season", state=SeasonState.submit, page_limit=400)
    db.add(season)
    await db.commit()
    await db.refresh(season)
    db.add(SeasonParticipant(season_id=season.id, user_id=test_admin.id))
    db.add(SeasonParticipant(season_id=season.id, user_id=test_user.id))
    await db.commit()
    return season


@pytest_asyncio.fixture
async def ranking_season(db, test_admin, test_user):
    """A season sitting in ranking with one book per participant."""
    season = Season(name="Rank Season", state=SeasonState.ranking, page_limit=400)
    db.add(season)
    await db.commit()
    await db.refresh(season)
    db.add(SeasonParticipant(season_id=season.id, user_id=test_admin.id))
    db.add(SeasonParticipant(season_id=season.id, user_id=test_user.id))
    db.add(
        Book(
            title="Book A",
            author="Auth A",
            page_count=100,
            submitter_id=test_admin.id,
            season_id=season.id,
        )
    )
    db.add(
        Book(
            title="Book B",
            author="Auth B",
            page_count=100,
            submitter_id=test_user.id,
            season_id=season.id,
        )
    )
    await db.commit()
    return season


# --- auto-submit ---------------------------------------------------------


async def test_auto_submit_noop_when_disabled(client_as_admin, submit_season, db, monkeypatch):
    """With dev tools off, auto-submit creates nothing."""
    monkeypatch.setattr(settings, "dev_tools_enabled", False)
    resp = await client_as_admin.post("/admin/god-mode/auto-submit")
    assert resp.status_code == 302
    assert await _book_count(db, submit_season.id) == 0


async def test_auto_submit_fills_all_participants(client_as_admin, submit_season, db, monkeypatch):
    """With dev tools on, every participant gets a book and the phase advances."""
    monkeypatch.setattr(settings, "dev_tools_enabled", True)
    resp = await client_as_admin.post("/admin/god-mode/auto-submit")
    assert resp.status_code == 302

    # submit_season enrolls test_admin + test_user → 2 books, both within the limit
    result = await db.execute(select(Book).where(Book.season_id == submit_season.id))
    books = result.scalars().all()
    assert len(books) == 2
    assert all(b.page_count <= submit_season.page_limit for b in books)

    await db.refresh(submit_season)
    assert submit_season.state == SeasonState.ranking  # all submitted → auto-advanced


# --- auto-rank -----------------------------------------------------------


async def test_auto_rank_noop_when_disabled(
    client_as_admin, ranking_season, db, test_admin, monkeypatch
):
    monkeypatch.setattr(settings, "dev_tools_enabled", False)
    resp = await client_as_admin.post("/admin/god-mode/auto-rank")
    assert resp.status_code == 302
    assert not await crud.get_borda_votes_for_user(db, test_admin.id, ranking_season.id)


async def test_auto_rank_fills_all_participants(
    client_as_admin, ranking_season, db, test_admin, test_user, monkeypatch
):
    monkeypatch.setattr(settings, "dev_tools_enabled", True)
    resp = await client_as_admin.post("/admin/god-mode/auto-rank")
    assert resp.status_code == 302

    assert await crud.get_borda_votes_for_user(db, test_admin.id, ranking_season.id)
    assert await crud.get_borda_votes_for_user(db, test_user.id, ranking_season.id)
    await db.refresh(ranking_season)
    assert ranking_season.state == SeasonState.bracket  # all ranked → auto-advanced
