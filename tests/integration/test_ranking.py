"""Integration tests for the Borda ranking flow."""
import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models import Book, BordaVote, Season, SeasonState


# ---------------------------------------------------------------------------
# Local fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def ranking_season(db, active_season, test_user, test_admin):
    """Two books, two users, season in ranking state.

    Returns (season, book1, book2) where book1 was submitted by test_user
    and book2 by test_admin.  Neither user has ranked yet.
    """
    book1 = Book(
        title="Book One",
        author="Auth A",
        page_count=200,
        submitter_id=test_user.id,
        season_id=active_season.id,
    )
    book2 = Book(
        title="Book Two",
        author="Auth B",
        page_count=200,
        submitter_id=test_admin.id,
        season_id=active_season.id,
    )
    db.add_all([book1, book2])
    active_season.state = SeasonState.ranking
    await db.commit()
    await db.refresh(book1)
    await db.refresh(book2)
    await db.refresh(active_season)
    return active_season, book1, book2


@pytest_asyncio.fixture
async def ranking_advance_setup(db, active_season, test_admin, extra_user):
    """Two books, two users (test_admin + extra_user), season in ranking state.

    extra_user has already ranked.  test_admin ranking via HTTP will be the
    last ranking submission, triggering the advance to bracket state.
    """
    book1 = Book(
        title="Admin Book",
        author="Auth A",
        page_count=200,
        submitter_id=test_admin.id,
        season_id=active_season.id,
    )
    book2 = Book(
        title="Extra Book",
        author="Auth B",
        page_count=200,
        submitter_id=extra_user.id,
        season_id=active_season.id,
    )
    db.add_all([book1, book2])
    active_season.state = SeasonState.ranking
    await db.flush()  # get IDs before referencing them in BordaVote

    # extra_user pre-ranks so only test_admin is left
    db.add(BordaVote(user_id=extra_user.id, season_id=active_season.id, book_id=book1.id, rank=1))
    db.add(BordaVote(user_id=extra_user.id, season_id=active_season.id, book_id=book2.id, rank=2))
    await db.commit()
    await db.refresh(book1)
    await db.refresh(book2)
    await db.refresh(active_season)
    return active_season, book1, book2


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_ranking_happy_path(client_as_user, ranking_season):
    """Valid ranking submission → 302 redirect, votes saved."""
    season, book1, book2 = ranking_season
    resp = await client_as_user.post(
        "/ranking",
        data={f"rank_{book1.id}": "1", f"rank_{book2.id}": "2"},
    )
    assert resp.status_code == 302
    assert resp.headers["location"] == "/ranking"


async def test_ranking_invalid_missing_rank(client_as_user, ranking_season):
    """Omitting a rank value triggers an error redirect."""
    season, book1, book2 = ranking_season
    # Only send rank for book1, omit book2
    resp = await client_as_user.post("/ranking", data={f"rank_{book1.id}": "1"})
    assert resp.status_code == 302
    assert "error=invalid" in resp.headers["location"]


async def test_ranking_duplicate_ignored(client_as_user, ranking_season):
    """A second ranking submission is silently ignored (original preserved)."""
    season, book1, book2 = ranking_season
    original = {f"rank_{book1.id}": "1", f"rank_{book2.id}": "2"}
    reversed_order = {f"rank_{book1.id}": "2", f"rank_{book2.id}": "1"}

    await client_as_user.post("/ranking", data=original)
    resp = await client_as_user.post("/ranking", data=reversed_order)
    # Second POST redirects without error
    assert resp.status_code == 302
    assert "error" not in resp.headers["location"]


async def test_ranking_advances_to_bracket(client_as_admin, ranking_advance_setup, db):
    """When the last user submits their ranking the season advances to bracket."""
    season, book1, book2 = ranking_advance_setup
    resp = await client_as_admin.post(
        "/ranking",
        data={f"rank_{book1.id}": "1", f"rank_{book2.id}": "2"},
    )
    assert resp.status_code == 302

    await db.refresh(season)
    assert season.state == SeasonState.bracket


async def test_borda_count_correctness(client_as_admin, ranking_advance_setup, db):
    """After advancing, the book ranked first by more voters gets seed 1.

    Setup: extra_user ranked book1 first; test_admin ranks book1 first again.
    Both voters prefer book1 → book1 should receive seed 1.
    """
    season, book1, book2 = ranking_advance_setup
    # test_admin also prefers book1
    await client_as_admin.post(
        "/ranking",
        data={f"rank_{book1.id}": "1", f"rank_{book2.id}": "2"},
    )

    # Verify seeds in DB
    from app.models import Seed

    result = await db.execute(
        select(Seed).where(Seed.season_id == season.id).order_by(Seed.seed)
    )
    seeds = result.scalars().all()
    assert len(seeds) == 2
    seed_map = {s.book_id: s.seed for s in seeds}
    assert seed_map[book1.id] == 1  # book1 preferred by both voters → seed 1
    assert seed_map[book2.id] == 2
