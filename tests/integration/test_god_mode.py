"""Integration tests for admin God Mode routes."""

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app import crud
from app.database import get_db
from app.main import app, get_user_or_none, require_admin, require_user
from app.models import Book, BordaVote, BracketVote, SeasonState


def make_client_with_real_auth(engine, current_user):
    """Like make_client but enforces the admin check for require_admin."""
    from fastapi import HTTPException

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_db():
        async with session_factory() as session:
            yield session

    async def override_user():
        return current_user

    async def override_require_admin():
        if current_user is None:
            raise HTTPException(status_code=302, headers={"Location": "/auth/login"})
        if not current_user.is_admin:
            raise HTTPException(status_code=403, detail="Admin access required.")
        return current_user

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_user_or_none] = override_user
    app.dependency_overrides[require_user] = override_user
    app.dependency_overrides[require_admin] = override_require_admin

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ---------------------------------------------------------------------------
# Submit God Mode
# ---------------------------------------------------------------------------


async def test_god_mode_submit_success(client_as_admin, active_season, test_user, db):
    """Admin can submit a book on behalf of another user."""
    resp = await client_as_admin.post(
        "/admin/god-mode/submit",
        data={
            "user_id": str(test_user.id),
            "title": "God Mode Book",
            "author": "Test Author",
            "page_count": "200",
        },
    )
    assert resp.status_code == 302

    result = await db.execute(
        select(Book).where(Book.submitter_id == test_user.id, Book.season_id == active_season.id)
    )
    book = result.scalar_one()
    assert book.title == "God Mode Book"
    assert book.author == "Test Author"


async def test_god_mode_submit_already_submitted(client_as_admin, active_season, test_user, db):
    """Can't submit twice for the same user."""
    book = Book(
        title="Existing",
        author="Author",
        page_count=100,
        submitter_id=test_user.id,
        season_id=active_season.id,
    )
    db.add(book)
    await db.commit()

    resp = await client_as_admin.post(
        "/admin/god-mode/submit",
        data={
            "user_id": str(test_user.id),
            "title": "Duplicate Attempt",
            "author": "Another Author",
            "page_count": "150",
        },
    )
    assert resp.status_code == 302

    result = await db.execute(
        select(Book).where(Book.submitter_id == test_user.id, Book.season_id == active_season.id)
    )
    assert len(result.scalars().all()) == 1  # still just the original


async def test_god_mode_submit_triggers_advance(
    client_as_admin, active_season, test_admin, test_user, db
):
    """When all participants have submitted, season advances to ranking."""
    # Admin submits their own book directly
    admin_book = Book(
        title="Admin Book",
        author="Admin Author",
        page_count=100,
        submitter_id=test_admin.id,
        season_id=active_season.id,
    )
    db.add(admin_book)
    await db.commit()

    # God mode submit for the last remaining user
    resp = await client_as_admin.post(
        "/admin/god-mode/submit",
        data={
            "user_id": str(test_user.id),
            "title": "User Book",
            "author": "User Author",
            "page_count": "200",
        },
    )
    assert resp.status_code == 302

    await db.refresh(active_season)
    assert active_season.state == SeasonState.ranking


async def test_god_mode_submit_non_admin_blocked(engine, test_user, active_season):
    """Non-admin users get 403 on god mode routes."""
    async with make_client_with_real_auth(engine, test_user) as client:
        resp = await client.post(
            "/admin/god-mode/submit",
            data={
                "user_id": str(test_user.id),
                "title": "Sneaky",
                "author": "Hacker",
                "page_count": "100",
            },
        )
    assert resp.status_code == 403
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Ranking God Mode
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def ranking_season(db, active_season, test_admin, test_user):
    """Season in ranking state with 2 books."""
    book_a = Book(
        title="Book A",
        author="Author A",
        page_count=100,
        submitter_id=test_admin.id,
        season_id=active_season.id,
    )
    book_b = Book(
        title="Book B",
        author="Author B",
        page_count=200,
        submitter_id=test_user.id,
        season_id=active_season.id,
    )
    db.add_all([book_a, book_b])
    active_season.state = SeasonState.ranking
    await db.commit()
    await db.refresh(book_a)
    await db.refresh(book_b)
    return active_season, book_a, book_b


async def test_god_mode_rank_success(client_as_admin, ranking_season, test_user, db):
    """Admin can rank books on behalf of a user."""
    season, book_a, book_b = ranking_season
    resp = await client_as_admin.post(
        "/admin/god-mode/rank",
        data={
            "user_id": str(test_user.id),
            f"rank_{book_a.id}": "1",
            f"rank_{book_b.id}": "2",
        },
    )
    assert resp.status_code == 302

    result = await db.execute(
        select(BordaVote).where(BordaVote.user_id == test_user.id, BordaVote.season_id == season.id)
    )
    votes = result.scalars().all()
    assert len(votes) == 2


async def test_god_mode_rank_already_ranked(client_as_admin, ranking_season, test_user, db):
    """Can't rank twice for the same user."""
    season, book_a, book_b = ranking_season

    await crud.save_borda_votes(db, test_user.id, season.id, [book_a.id, book_b.id])

    resp = await client_as_admin.post(
        "/admin/god-mode/rank",
        data={
            "user_id": str(test_user.id),
            f"rank_{book_a.id}": "2",
            f"rank_{book_b.id}": "1",
        },
    )
    assert resp.status_code == 302

    # Still only 2 votes (the originals)
    result = await db.execute(
        select(BordaVote).where(BordaVote.user_id == test_user.id, BordaVote.season_id == season.id)
    )
    votes = result.scalars().all()
    assert len(votes) == 2


async def test_god_mode_rank_invalid_ranking(client_as_admin, ranking_season, test_user, db):
    """Invalid ranking (wrong ranks) is rejected."""
    season, book_a, book_b = ranking_season
    resp = await client_as_admin.post(
        "/admin/god-mode/rank",
        data={
            "user_id": str(test_user.id),
            f"rank_{book_a.id}": "1",
            f"rank_{book_b.id}": "1",  # duplicate rank
        },
    )
    assert resp.status_code == 302

    result = await db.execute(
        select(BordaVote).where(BordaVote.user_id == test_user.id, BordaVote.season_id == season.id)
    )
    assert len(result.scalars().all()) == 0  # nothing saved


async def test_god_mode_rank_triggers_advance(
    client_as_admin, ranking_season, test_admin, test_user, db
):
    """When all participants have ranked, season advances to bracket."""
    season, book_a, book_b = ranking_season

    # Admin ranks their own books
    await crud.save_borda_votes(db, test_admin.id, season.id, [book_a.id, book_b.id])

    # God mode rank for the last user
    resp = await client_as_admin.post(
        "/admin/god-mode/rank",
        data={
            "user_id": str(test_user.id),
            f"rank_{book_a.id}": "1",
            f"rank_{book_b.id}": "2",
        },
    )
    assert resp.status_code == 302

    await db.refresh(season)
    assert season.state == SeasonState.bracket


# ---------------------------------------------------------------------------
# Bracket Vote God Mode
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def bracket_season(db, active_season, test_admin, test_user):
    """Season in bracket state with a matchup ready for voting."""
    from app.models import BracketMatchup, Seed

    book_a = Book(
        title="Book A",
        author="Author A",
        page_count=100,
        submitter_id=test_admin.id,
        season_id=active_season.id,
    )
    book_b = Book(
        title="Book B",
        author="Author B",
        page_count=200,
        submitter_id=test_user.id,
        season_id=active_season.id,
    )
    db.add_all([book_a, book_b])
    await db.commit()
    await db.refresh(book_a)
    await db.refresh(book_b)

    seed_a = Seed(season_id=active_season.id, book_id=book_a.id, seed=1)
    seed_b = Seed(season_id=active_season.id, book_id=book_b.id, seed=2)
    db.add_all([seed_a, seed_b])

    matchup = BracketMatchup(
        season_id=active_season.id,
        round=1,
        position=1,
        book_a_id=book_a.id,
        book_b_id=book_b.id,
    )
    db.add(matchup)
    active_season.state = SeasonState.bracket
    await db.commit()
    await db.refresh(matchup)

    return active_season, matchup, book_a, book_b


async def test_god_mode_bracket_vote_success(client_as_admin, bracket_season, test_user, db):
    """Admin can vote in bracket on behalf of a user."""
    season, matchup, book_a, book_b = bracket_season
    resp = await client_as_admin.post(
        "/admin/god-mode/bracket-vote",
        data={
            "user_id": str(test_user.id),
            "matchup_id": str(matchup.id),
            "book_id": str(book_a.id),
        },
    )
    assert resp.status_code == 302

    result = await db.execute(
        select(BracketVote).where(
            BracketVote.user_id == test_user.id, BracketVote.matchup_id == matchup.id
        )
    )
    vote = result.scalar_one()
    assert vote.book_id == book_a.id


async def test_god_mode_bracket_vote_double_blocked(client_as_admin, bracket_season, test_user, db):
    """Can't vote twice for the same user on the same matchup."""
    season, matchup, book_a, book_b = bracket_season

    await crud.save_bracket_vote(db, test_user.id, matchup.id, book_a.id)

    resp = await client_as_admin.post(
        "/admin/god-mode/bracket-vote",
        data={
            "user_id": str(test_user.id),
            "matchup_id": str(matchup.id),
            "book_id": str(book_b.id),
        },
    )
    assert resp.status_code == 302

    result = await db.execute(
        select(BracketVote).where(
            BracketVote.user_id == test_user.id, BracketVote.matchup_id == matchup.id
        )
    )
    vote = result.scalar_one()
    assert vote.book_id == book_a.id  # original vote unchanged
