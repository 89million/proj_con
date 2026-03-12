"""Integration tests for the bracket voting flow."""
from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models import Book, BracketMatchup, BracketVote, ReadBook, Season, SeasonState


# ---------------------------------------------------------------------------
# Local fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def bracket_setup(db, active_season, test_user, test_admin):
    """Two books, one real matchup, season in bracket state.

    Returns (season, book1, book2, matchup).
    test_admin submitted book1, test_user submitted book2.
    Neither user has voted yet.
    """
    book1 = Book(
        title="Book Alpha",
        author="Auth A",
        page_count=200,
        submitter_id=test_admin.id,
        season_id=active_season.id,
    )
    book2 = Book(
        title="Book Beta",
        author="Auth B",
        page_count=200,
        submitter_id=test_user.id,
        season_id=active_season.id,
    )
    db.add_all([book1, book2])
    active_season.state = SeasonState.bracket
    await db.flush()

    matchup = BracketMatchup(
        season_id=active_season.id,
        round=1,
        position=1,
        book_a_id=book1.id,
        book_b_id=book2.id,
    )
    db.add(matchup)
    await db.commit()
    await db.refresh(book1)
    await db.refresh(book2)
    await db.refresh(matchup)
    await db.refresh(active_season)
    return active_season, book1, book2, matchup


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_bracket_vote_happy_path(client_as_user, bracket_setup):
    """Voting for a valid book in a matchup → 302 redirect."""
    season, book1, book2, matchup = bracket_setup
    resp = await client_as_user.post(
        f"/bracket/vote/{matchup.id}", data={"book_id": str(book1.id)}
    )
    assert resp.status_code == 302
    assert resp.headers["location"] == "/bracket"


async def test_bracket_vote_invalid_book(client_as_user, bracket_setup):
    """Voting for a book_id not in the matchup returns 400."""
    season, book1, book2, matchup = bracket_setup
    resp = await client_as_user.post(
        f"/bracket/vote/{matchup.id}", data={"book_id": "9999"}
    )
    assert resp.status_code == 400


async def test_bracket_double_vote_ignored(client_as_user, bracket_setup, db):
    """A second vote on the same matchup is silently ignored (original preserved)."""
    season, book1, book2, matchup = bracket_setup

    await client_as_user.post(
        f"/bracket/vote/{matchup.id}", data={"book_id": str(book1.id)}
    )
    resp = await client_as_user.post(
        f"/bracket/vote/{matchup.id}", data={"book_id": str(book2.id)}
    )
    assert resp.status_code == 302

    # Original vote (book1) is preserved
    result = await db.execute(select(BracketVote).where(BracketVote.matchup_id == matchup.id))
    votes = result.scalars().all()
    assert len(votes) == 1
    assert votes[0].book_id == book1.id


async def test_bracket_final_completes_season(client_as_user, bracket_setup, db):
    """When all users vote on the only matchup the season moves to complete."""
    season, book1, book2, matchup = bracket_setup

    # test_admin pre-votes via DB so only test_user's HTTP vote is left
    admin_vote = BracketVote(
        user_id=bracket_setup[0].id,  # season — need test_admin id
        matchup_id=matchup.id,
        book_id=book1.id,
    )
    # Get test_admin from DB
    from app.models import User

    result = await db.execute(select(User).where(User.email == "admin@test.com"))
    test_admin = result.scalar_one()
    db.add(
        BracketVote(user_id=test_admin.id, matchup_id=matchup.id, book_id=book1.id)
    )
    await db.commit()

    # test_user casts the deciding vote
    resp = await client_as_user.post(
        f"/bracket/vote/{matchup.id}", data={"book_id": str(book1.id)}
    )
    assert resp.status_code == 302

    # Season should now be complete
    await db.refresh(season)
    assert season.state == SeasonState.complete

    # Winner should appear in read_books with won=True
    result = await db.execute(
        select(ReadBook).where(ReadBook.title == book1.title, ReadBook.won == True)
    )
    winner_entry = result.scalar_one_or_none()
    assert winner_entry is not None


async def test_tiebreak_earliest_vote_wins(client_as_user, bracket_setup, db):
    """On a tie, the book whose first vote arrived earliest wins."""
    season, book1, book2, matchup = bracket_setup

    # test_admin pre-votes for book2 with an early timestamp
    from app.models import User

    result = await db.execute(select(User).where(User.email == "admin@test.com"))
    test_admin = result.scalar_one()

    early_time = datetime(2020, 1, 1, 0, 0, 0)
    db.add(
        BracketVote(
            user_id=test_admin.id,
            matchup_id=matchup.id,
            book_id=book2.id,
            voted_at=early_time,
        )
    )
    await db.commit()

    # test_user votes for book1 (later timestamp, set by server_default ~now)
    resp = await client_as_user.post(
        f"/bracket/vote/{matchup.id}", data={"book_id": str(book1.id)}
    )
    assert resp.status_code == 302

    # Equal votes (1 each); book2's first vote was earlier → book2 should win
    await db.refresh(season)
    assert season.state == SeasonState.complete

    result = await db.execute(
        select(ReadBook).where(ReadBook.title == book2.title, ReadBook.won == True)
    )
    assert result.scalar_one_or_none() is not None
