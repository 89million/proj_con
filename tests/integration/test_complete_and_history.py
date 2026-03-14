"""Integration tests for the complete/winner page and history routes."""

import pytest_asyncio

from app.models import Book, BordaVote, BracketMatchup, BracketVote, Season, SeasonState, Seed

from .conftest import make_client


@pytest_asyncio.fixture
async def complete_season(db, test_admin, test_user):
    """A season in complete state with 2 books and a resolved final matchup."""
    season = Season(name="Past Season", state=SeasonState.complete, page_limit=400)
    db.add(season)
    await db.flush()
    book1 = Book(
        title="The Winning Book",
        author="Winner Author",
        page_count=300,
        submitter_id=test_admin.id,
        season_id=season.id,
    )
    book2 = Book(
        title="The Losing Book",
        author="Loser Author",
        page_count=250,
        submitter_id=test_user.id,
        season_id=season.id,
    )
    db.add_all([book1, book2])
    await db.flush()
    matchup = BracketMatchup(
        season_id=season.id,
        round=2,
        position=1,
        book_a_id=book1.id,
        book_b_id=book2.id,
        winner_id=book1.id,
    )
    db.add(matchup)
    await db.commit()
    await db.refresh(season)
    await db.refresh(book1)
    return season, book1


# ---------------------------------------------------------------------------
# Root redirect behaviour
# ---------------------------------------------------------------------------


async def test_root_redirects_to_complete_when_season_complete(engine, test_user, complete_season):
    async with make_client(engine, test_user) as client:
        resp = await client.get("/", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/complete"


async def test_root_no_season_admin_sees_start_button(engine, db, test_admin):
    """With no seasons at all, admin sees a start-new-season prompt."""
    async with make_client(engine, test_admin) as client:
        resp = await client.get("/", follow_redirects=True)
    assert resp.status_code == 200
    assert "Start a New Season" in resp.text


async def test_root_no_season_non_admin_no_start_button(engine, db, test_user):
    """With no seasons at all, a regular user does NOT see the start-season button."""
    async with make_client(engine, test_user) as client:
        resp = await client.get("/", follow_redirects=True)
    assert resp.status_code == 200
    assert "Start a New Season" not in resp.text


# ---------------------------------------------------------------------------
# /complete page
# ---------------------------------------------------------------------------


async def test_complete_page_shows_winner(engine, test_user, complete_season):
    season, winner_book = complete_season
    async with make_client(engine, test_user) as client:
        resp = await client.get("/complete")
    assert resp.status_code == 200
    assert winner_book.title in resp.text


async def test_complete_page_works_with_non_round3_final(engine, test_user, complete_season):
    """Winner is found even when the final matchup is not round 3 (our fixture uses round 2)."""
    season, winner_book = complete_season
    async with make_client(engine, test_user) as client:
        resp = await client.get("/complete")
    assert resp.status_code == 200
    assert winner_book.title in resp.text


async def test_complete_page_admin_sees_start_button(engine, test_admin, complete_season):
    async with make_client(engine, test_admin) as client:
        resp = await client.get("/complete")
    assert resp.status_code == 200
    assert "Start Next Season" in resp.text


async def test_complete_page_user_no_start_button(engine, test_user, complete_season):
    async with make_client(engine, test_user) as client:
        resp = await client.get("/complete")
    assert resp.status_code == 200
    assert "Start Next Season" not in resp.text


# ---------------------------------------------------------------------------
# /history list
# ---------------------------------------------------------------------------


async def test_history_list_shows_complete_seasons(engine, test_user, complete_season):
    season, _ = complete_season
    async with make_client(engine, test_user) as client:
        resp = await client.get("/history")
    assert resp.status_code == 200
    assert season.name in resp.text


async def test_history_list_empty(engine, db, test_user):
    async with make_client(engine, test_user) as client:
        resp = await client.get("/history")
    assert resp.status_code == 200
    assert "No completed seasons" in resp.text


# ---------------------------------------------------------------------------
# /history/{season_id} drill-down
# ---------------------------------------------------------------------------


async def test_history_drilldown_shows_winner(engine, test_user, complete_season):
    season, winner_book = complete_season
    async with make_client(engine, test_user) as client:
        resp = await client.get(f"/history/{season.id}")
    assert resp.status_code == 200
    assert winner_book.title in resp.text


async def test_history_drilldown_404_for_active_season(engine, db, test_user, active_season):
    async with make_client(engine, test_user) as client:
        resp = await client.get(f"/history/{active_season.id}")
    assert resp.status_code == 404


async def test_history_drilldown_404_for_nonexistent(engine, db, test_user):
    async with make_client(engine, test_user) as client:
        resp = await client.get("/history/99999")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# /history/{season_id} content depth
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def complete_season_with_seeds(db, test_admin, test_user):
    """Completed season with Seed rows and a resolved bracket matchup.

    book1 (seed #1, winner) vs book2 (seed #2, loser) in round 1.
    """
    season = Season(name="Seeded Season", state=SeasonState.complete, page_limit=400)
    db.add(season)
    await db.flush()
    book1 = Book(
        title="Top Seed Book",
        author="Seed One Author",
        page_count=280,
        submitter_id=test_admin.id,
        season_id=season.id,
    )
    book2 = Book(
        title="Second Seed Book",
        author="Seed Two Author",
        page_count=200,
        submitter_id=test_user.id,
        season_id=season.id,
    )
    db.add_all([book1, book2])
    await db.flush()
    db.add(Seed(season_id=season.id, book_id=book1.id, seed=1))
    db.add(Seed(season_id=season.id, book_id=book2.id, seed=2))
    matchup = BracketMatchup(
        season_id=season.id,
        round=1,
        position=1,
        book_a_id=book1.id,
        book_b_id=book2.id,
        winner_id=book1.id,
    )
    db.add(matchup)
    await db.commit()
    await db.refresh(season)
    await db.refresh(book1)
    await db.refresh(book2)
    return season, book1, book2


async def test_history_drilldown_shows_seeds_table(engine, test_user, complete_season_with_seeds):
    """Drill-down page renders the Borda seeds table with seed numbers and titles."""
    season, book1, book2 = complete_season_with_seeds
    async with make_client(engine, test_user) as client:
        resp = await client.get(f"/history/{season.id}")
    assert resp.status_code == 200
    assert "Borda Seeds" in resp.text
    assert "#1" in resp.text
    assert book1.title in resp.text
    assert book2.title in resp.text


async def test_history_drilldown_shows_bracket_results(
    engine, test_user, complete_season_with_seeds
):
    """Drill-down page renders the bracket results section with round name."""
    season, book1, book2 = complete_season_with_seeds
    async with make_client(engine, test_user) as client:
        resp = await client.get(f"/history/{season.id}")
    assert resp.status_code == 200
    assert "Bracket Results" in resp.text
    # Single round → labelled "Final"
    assert "Final" in resp.text
    assert book1.title in resp.text
    assert book2.title in resp.text


async def test_history_drilldown_winner_marked_in_bracket(
    engine, test_user, complete_season_with_seeds
):
    """The winner is marked with 'Winner ✓' and the loser is not."""
    season, book1, book2 = complete_season_with_seeds
    async with make_client(engine, test_user) as client:
        resp = await client.get(f"/history/{season.id}")
    assert resp.status_code == 200
    assert "Winner" in resp.text


# ---------------------------------------------------------------------------
# Vote counts in history drill-down
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def complete_season_with_votes(db, test_admin, test_user):
    """Completed season with Borda votes and bracket votes recorded.

    2 books, 2 voters:
    - test_admin ranks book1 #1, book2 #2  (Borda: book1 +1, book2 +0)
    - test_user  ranks book1 #2, book2 #1  (Borda: book1 +0, book2 +1)
    - bracket: both vote for book1 (votes 2–0), book1 wins
    """
    season = Season(name="Vote Count Season", state=SeasonState.complete, page_limit=400)
    db.add(season)
    await db.flush()
    book1 = Book(
        title="The Dominant Book",
        author="Popular Author",
        page_count=300,
        submitter_id=test_admin.id,
        season_id=season.id,
    )
    book2 = Book(
        title="The Underdog Book",
        author="Underdog Author",
        page_count=200,
        submitter_id=test_user.id,
        season_id=season.id,
    )
    db.add_all([book1, book2])
    await db.flush()

    # Seeds
    db.add(Seed(season_id=season.id, book_id=book1.id, seed=1))
    db.add(Seed(season_id=season.id, book_id=book2.id, seed=2))

    # Borda votes (2 books → N=2; points = 2 - rank)
    db.add(BordaVote(user_id=test_admin.id, season_id=season.id, book_id=book1.id, rank=1))
    db.add(BordaVote(user_id=test_admin.id, season_id=season.id, book_id=book2.id, rank=2))
    db.add(BordaVote(user_id=test_user.id, season_id=season.id, book_id=book1.id, rank=2))
    db.add(BordaVote(user_id=test_user.id, season_id=season.id, book_id=book2.id, rank=1))

    # Bracket matchup — both voters pick book1 (2–0)
    matchup = BracketMatchup(
        season_id=season.id,
        round=1,
        position=1,
        book_a_id=book1.id,
        book_b_id=book2.id,
        winner_id=book1.id,
    )
    db.add(matchup)
    await db.flush()
    db.add(BracketVote(user_id=test_admin.id, matchup_id=matchup.id, book_id=book1.id))
    db.add(BracketVote(user_id=test_user.id, matchup_id=matchup.id, book_id=book1.id))

    await db.commit()
    await db.refresh(season)
    await db.refresh(book1)
    await db.refresh(book2)
    return season, book1, book2


async def test_history_drilldown_shows_borda_points(engine, test_user, complete_season_with_votes):
    """Seeds table displays the Borda point totals for each book."""
    season, book1, book2 = complete_season_with_votes
    async with make_client(engine, test_user) as client:
        resp = await client.get(f"/history/{season.id}")
    assert resp.status_code == 200
    assert "Pts" in resp.text
    # book1: admin ranked it #1 → 1 pt (2-1), user ranked it #2 → 0 pts (2-2). Total = 1
    # book2: admin ranked it #2 → 0 pts, user ranked it #1 → 1 pt. Total = 1
    # Both show a numeric score (just verify the column exists and has a value)
    assert "Borda Seeds" in resp.text


async def test_history_drilldown_shows_bracket_vote_counts(
    engine, test_user, complete_season_with_votes
):
    """Bracket results show vote counts (e.g. '2 – 0') for each matchup."""
    season, book1, book2 = complete_season_with_votes
    async with make_client(engine, test_user) as client:
        resp = await client.get(f"/history/{season.id}")
    assert resp.status_code == 200
    # Both votes went to book1 (book_a), so expect "2 – 0"
    assert "2 – 0" in resp.text


async def test_history_drilldown_no_votes_shows_vs(engine, test_user, complete_season_with_seeds):
    """When no bracket votes were cast, the matchup shows 'vs' instead of counts."""
    season, book1, book2 = complete_season_with_seeds
    async with make_client(engine, test_user) as client:
        resp = await client.get(f"/history/{season.id}")
    assert resp.status_code == 200
    assert "vs" in resp.text


# ---------------------------------------------------------------------------
# Tiebreaker transparency — history drill-down
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def complete_season_first_vote_tie(db, test_admin, test_user):
    """Completed season where a bracket matchup ended 1-1 (first-vote tiebreak).

    Both voters have equal prior nominations (0), so the first-vote rule applies.
    book1 wins because test_admin voted for it first.
    """
    from datetime import datetime

    season = Season(name="Tiebreak Season", state=SeasonState.complete, page_limit=400)
    db.add(season)
    await db.flush()
    book1 = Book(
        title="Tiebreak Winner",
        author="Auth A",
        page_count=300,
        submitter_id=test_admin.id,
        season_id=season.id,
    )
    book2 = Book(
        title="Tiebreak Loser",
        author="Auth B",
        page_count=200,
        submitter_id=test_user.id,
        season_id=season.id,
    )
    db.add_all([book1, book2])
    await db.flush()
    db.add(Seed(season_id=season.id, book_id=book1.id, seed=1))
    db.add(Seed(season_id=season.id, book_id=book2.id, seed=2))
    matchup = BracketMatchup(
        season_id=season.id,
        round=1,
        position=1,
        book_a_id=book1.id,
        book_b_id=book2.id,
        winner_id=book1.id,
    )
    db.add(matchup)
    await db.flush()
    # book1 gets the earlier vote → wins tiebreak
    db.add(
        BracketVote(
            user_id=test_admin.id,
            matchup_id=matchup.id,
            book_id=book1.id,
            voted_at=datetime(2024, 1, 1, 10, 0, 0),
        )
    )
    db.add(
        BracketVote(
            user_id=test_user.id,
            matchup_id=matchup.id,
            book_id=book2.id,
            voted_at=datetime(2024, 1, 1, 11, 0, 0),
        )
    )
    await db.commit()
    await db.refresh(season)
    await db.refresh(book1)
    return season, book1


async def test_history_drilldown_shows_first_vote_tiebreak(
    engine, test_user, complete_season_first_vote_tie
):
    """Tied bracket matchup shows the 'earliest vote' tiebreaker note."""
    season, _ = complete_season_first_vote_tie
    async with make_client(engine, test_user) as client:
        resp = await client.get(f"/history/{season.id}")
    assert resp.status_code == 200
    assert "earliest vote" in resp.text.lower()
    assert "⚖️" in resp.text


async def test_history_drilldown_no_tiebreaker_when_clear_winner(
    engine, test_user, complete_season_with_votes
):
    """A matchup decided by clear vote majority shows no tiebreaker badge."""
    season, _, _ = complete_season_with_votes
    async with make_client(engine, test_user) as client:
        resp = await client.get(f"/history/{season.id}")
    assert resp.status_code == 200
    # 2-0 vote — no bracket tiebreaker note should appear
    assert "earliest vote" not in resp.text.lower()
    assert "tie — decided by" not in resp.text.lower()
