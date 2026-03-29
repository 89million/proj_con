"""Integration tests for the season recap page."""

import pytest_asyncio

from app.models import (
    Book,
    BordaVote,
    BracketMatchup,
    BracketVote,
    Season,
    SeasonParticipant,
    SeasonState,
    Seed,
)


@pytest_asyncio.fixture
async def completed_season(db, test_admin, test_user):
    """A completed season with bracket data for recap testing."""
    season = Season(name="Recap Test", state=SeasonState.submit, page_limit=400)
    db.add(season)
    await db.commit()
    await db.refresh(season)

    db.add(SeasonParticipant(season_id=season.id, user_id=test_admin.id))
    db.add(SeasonParticipant(season_id=season.id, user_id=test_user.id))

    books = []
    for i, (title, author, submitter) in enumerate(
        [
            ("Winner Book", "Auth A", test_admin),
            ("Runner Up", "Auth B", test_user),
            ("Third Place", "Auth C", test_admin),
            ("Fourth Place", "Auth D", test_user),
        ]
    ):
        b = Book(
            title=title,
            author=author,
            page_count=200,
            submitter_id=submitter.id,
            season_id=season.id,
        )
        db.add(b)
        books.append(b)
    await db.flush()

    # Seeds
    for seed_num, book in enumerate(books, start=1):
        db.add(Seed(season_id=season.id, book_id=book.id, seed=seed_num))

    # Borda votes — different rankings so "Most Controversial" has variance
    # Admin: 1,2,3,4 | User: 1,4,2,3 (book[1] is controversial: ranked 2 vs 4)
    admin_ranks = [1, 2, 3, 4]
    user_ranks = [1, 4, 2, 3]
    for rank, book in zip(admin_ranks, books):
        db.add(BordaVote(user_id=test_admin.id, season_id=season.id, book_id=book.id, rank=rank))
    for rank, book in zip(user_ranks, books):
        db.add(BordaVote(user_id=test_user.id, season_id=season.id, book_id=book.id, rank=rank))

    # Bracket: semi-final matchups
    m1 = BracketMatchup(
        season_id=season.id,
        round=1,
        position=1,
        book_a_id=books[0].id,
        book_b_id=books[3].id,
        winner_id=books[0].id,
    )
    m2 = BracketMatchup(
        season_id=season.id,
        round=1,
        position=2,
        book_a_id=books[1].id,
        book_b_id=books[2].id,
        winner_id=books[1].id,
    )
    db.add_all([m1, m2])
    await db.flush()

    # Votes for matchups
    for user in [test_admin, test_user]:
        db.add(BracketVote(user_id=user.id, matchup_id=m1.id, book_id=books[0].id))
        db.add(BracketVote(user_id=user.id, matchup_id=m2.id, book_id=books[1].id))

    # Final
    final = BracketMatchup(
        season_id=season.id,
        round=2,
        position=1,
        book_a_id=books[0].id,
        book_b_id=books[1].id,
        winner_id=books[0].id,
    )
    db.add(final)
    await db.flush()

    db.add(BracketVote(user_id=test_admin.id, matchup_id=final.id, book_id=books[0].id))
    db.add(BracketVote(user_id=test_user.id, matchup_id=final.id, book_id=books[1].id))

    season.state = SeasonState.complete
    await db.commit()

    for b in books:
        await db.refresh(b)
    await db.refresh(season)
    return season, books


async def test_recap_page_loads(client_as_user, completed_season, db):
    """Recap page returns 200 for a completed season."""
    season, _ = completed_season
    resp = await client_as_user.get(f"/season/{season.id}/recap")
    assert resp.status_code == 200
    assert "Recap" in resp.text
    assert "Winner Book" in resp.text


async def test_recap_incomplete_season_404(client_as_user, db, test_admin, test_user):
    """Recap page returns 404 for a non-complete season."""
    season = Season(name="In Progress", state=SeasonState.submit, page_limit=400)
    db.add(season)
    await db.commit()
    await db.refresh(season)

    resp = await client_as_user.get(f"/season/{season.id}/recap")
    assert resp.status_code == 404


async def test_recap_has_stats(client_as_user, completed_season, db):
    """Recap page includes expected stat categories."""
    season, _ = completed_season
    resp = await client_as_user.get(f"/season/{season.id}/recap")
    assert resp.status_code == 200
    text = resp.text
    # Should have at least closest matchup and participation stats
    assert "Closest Matchup" in text
    assert "Participation" in text
    assert "Most Controversial" in text
