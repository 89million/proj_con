"""Integration tests that assert specific content appears in rendered templates.

These tests exercise the "frontend" — they follow redirects and inspect
the HTML body to confirm the right information is shown to users.
"""

import pytest_asyncio

from app.models import Book, BracketMatchup, Season, SeasonState, Seed

from .conftest import make_client

# ---------------------------------------------------------------------------
# Shared local fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def two_book_ranking_season(db, active_season, test_user, test_admin):
    """Two books submitted; season advanced to ranking state."""
    book1 = Book(
        title="Alpha Book",
        author="First Author",
        page_count=200,
        submitter_id=test_user.id,
        season_id=active_season.id,
    )
    book2 = Book(
        title="Beta Book",
        author="Second Author",
        page_count=250,
        submitter_id=test_admin.id,
        season_id=active_season.id,
    )
    db.add_all([book1, book2])
    active_season.state = SeasonState.ranking
    await db.commit()
    await db.refresh(book1)
    await db.refresh(book2)
    return active_season, book1, book2


@pytest_asyncio.fixture
async def single_round_bracket(db, active_season, test_user, test_admin):
    """One matchup in round 1 (max_round=1 → labelled 'Final')."""
    book1 = Book(
        title="Final Book A",
        author="Auth A",
        page_count=200,
        submitter_id=test_user.id,
        season_id=active_season.id,
    )
    book2 = Book(
        title="Final Book B",
        author="Auth B",
        page_count=200,
        submitter_id=test_admin.id,
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
    return active_season, book1, book2, matchup


@pytest_asyncio.fixture
async def two_round_bracket(db, active_season, test_user, test_admin, extra_user):
    """3 books → 2 rounds (ceil(log2(3))=2), so round 1 is labelled 'Semifinals'."""
    book1 = Book(
        title="Semis Book A",
        author="Auth A",
        page_count=200,
        submitter_id=test_user.id,
        season_id=active_season.id,
    )
    book2 = Book(
        title="Semis Book B",
        author="Auth B",
        page_count=200,
        submitter_id=test_admin.id,
        season_id=active_season.id,
    )
    book3 = Book(
        title="Semis Book C",
        author="Auth C",
        page_count=200,
        submitter_id=extra_user.id,
        season_id=active_season.id,
    )
    from app.models import SeasonParticipant

    # Enroll extra_user as participant
    db.add(SeasonParticipant(season_id=active_season.id, user_id=extra_user.id))
    db.add_all([book1, book2, book3])
    active_season.state = SeasonState.bracket
    await db.flush()
    # Seeds (needed for seed_map in template)
    db.add_all(
        [
            Seed(season_id=active_season.id, book_id=book1.id, seed=1),
            Seed(season_id=active_season.id, book_id=book2.id, seed=2),
            Seed(season_id=active_season.id, book_id=book3.id, seed=3),
        ]
    )
    # Round 1: book1 gets a bye, book2 vs book3
    matchup_bye = BracketMatchup(
        season_id=active_season.id,
        round=1,
        position=1,
        book_a_id=book1.id,
        book_b_id=book1.id,
        winner_id=book1.id,
    )
    matchup_r1 = BracketMatchup(
        season_id=active_season.id,
        round=1,
        position=2,
        book_a_id=book2.id,
        book_b_id=book3.id,
    )
    db.add_all([matchup_bye, matchup_r1])
    await db.commit()
    await db.refresh(book1)
    await db.refresh(book2)
    await db.refresh(book3)
    return active_season, book1, book2, book3


@pytest_asyncio.fixture
async def complete_season_with_submitter(db, test_admin, test_user):
    """Completed season; winner book was submitted by test_admin."""
    season = Season(name="Trophy Season", state=SeasonState.complete, page_limit=400)
    db.add(season)
    await db.flush()
    winner = Book(
        title="The Great Winner",
        author="Prize Author",
        page_count=312,
        submitter_id=test_admin.id,
        season_id=season.id,
    )
    loser = Book(
        title="The Runner Up",
        author="Second Author",
        page_count=250,
        submitter_id=test_user.id,
        season_id=season.id,
    )
    db.add_all([winner, loser])
    await db.flush()
    matchup = BracketMatchup(
        season_id=season.id,
        round=1,
        position=1,
        book_a_id=winner.id,
        book_b_id=loser.id,
        winner_id=winner.id,
    )
    db.add(matchup)
    await db.commit()
    await db.refresh(season)
    await db.refresh(winner)
    return season, winner


# ---------------------------------------------------------------------------
# Submit page
# ---------------------------------------------------------------------------


async def test_submit_page_shows_season_info(client_as_user, active_season):
    """Submit page displays season name and page limit."""
    resp = await client_as_user.get("/submit")
    assert resp.status_code == 200
    assert active_season.name in resp.text
    assert str(active_season.page_limit) in resp.text


async def test_submit_page_shows_user_book_after_submission(client_as_user, active_season):
    """After submitting, the user sees their own book title on the page."""
    await client_as_user.post(
        "/submit",
        data={"title": "My Chosen Book", "author": "Great Author", "page_count": 200},
    )
    resp = await client_as_user.get("/submit")
    assert resp.status_code == 200
    assert "My Chosen Book" in resp.text
    assert "You submitted" in resp.text


async def test_submit_page_shows_other_submissions(client_as_user, active_season, db, test_admin):
    """Books submitted by other participants are visible to all users."""
    db.add(
        Book(
            title="Admin Selection",
            author="Admin Author",
            page_count=300,
            submitter_id=test_admin.id,
            season_id=active_season.id,
        )
    )
    await db.commit()

    resp = await client_as_user.get("/submit")
    assert resp.status_code == 200
    assert "Admin Selection" in resp.text
    assert "Submissions so far" in resp.text


async def test_submit_page_error_shown_on_page_limit_breach(client_as_user, active_season):
    """Submitting a book over the page limit shows an error without losing form values."""
    resp = await client_as_user.post(
        "/submit",
        data={"title": "Huge Tome", "author": "Verbose Author", "page_count": 401},
    )
    assert resp.status_code == 200
    assert "400" in resp.text  # page limit in error message
    assert "Huge Tome" in resp.text  # title repopulated


# ---------------------------------------------------------------------------
# Ranking page
# ---------------------------------------------------------------------------


async def test_ranking_page_shows_both_books(client_as_user, two_book_ranking_season):
    """Ranking page renders all book titles for the user to sort."""
    _, book1, book2 = two_book_ranking_season
    resp = await client_as_user.get("/ranking")
    assert resp.status_code == 200
    assert book1.title in resp.text
    assert book2.title in resp.text


async def test_ranking_page_shows_already_ranked_state(client_as_user, two_book_ranking_season):
    """After submitting a ranking the user sees their ranking (not the form)."""
    _, book1, book2 = two_book_ranking_season
    await client_as_user.post(
        "/ranking",
        data={f"rank_{book1.id}": "1", f"rank_{book2.id}": "2"},
    )
    resp = await client_as_user.get("/ranking")
    assert resp.status_code == 200
    assert "Your ranking" in resp.text


# ---------------------------------------------------------------------------
# Bracket page — round labels
# ---------------------------------------------------------------------------


async def test_bracket_page_shows_matchup_books(client_as_user, single_round_bracket):
    """Both books in the active matchup appear on the bracket page."""
    _, book1, book2, _ = single_round_bracket
    resp = await client_as_user.get("/bracket")
    assert resp.status_code == 200
    assert book1.title in resp.text
    assert book2.title in resp.text


async def test_bracket_page_labels_single_round_as_final(client_as_user, single_round_bracket):
    """A bracket with only one round labels it 'Final' (max_round=1)."""
    resp = await client_as_user.get("/bracket")
    assert resp.status_code == 200
    assert "Final" in resp.text


async def test_bracket_page_labels_first_round_as_semifinals(client_as_user, two_round_bracket):
    """A bracket with two rounds labels round 1 'Semifinals' (max_round=2)."""
    resp = await client_as_user.get("/bracket")
    assert resp.status_code == 200
    assert "Semifinals" in resp.text


# ---------------------------------------------------------------------------
# Complete page — content depth
# ---------------------------------------------------------------------------


async def test_complete_page_shows_season_name(engine, test_user, complete_season_with_submitter):
    """The complete page displays the season name."""
    season, _ = complete_season_with_submitter
    async with make_client(engine, test_user) as client:
        resp = await client.get("/complete")
    assert resp.status_code == 200
    assert season.name in resp.text


async def test_complete_page_shows_winner_page_count(
    engine, test_user, complete_season_with_submitter
):
    """The winner card shows the book's page count."""
    _, winner = complete_season_with_submitter
    async with make_client(engine, test_user) as client:
        resp = await client.get("/complete")
    assert resp.status_code == 200
    assert str(winner.page_count) in resp.text


async def test_complete_page_shows_view_past_seasons_link(
    engine, test_user, complete_season_with_submitter
):
    """The complete page links to /history."""
    async with make_client(engine, test_user) as client:
        resp = await client.get("/complete")
    assert resp.status_code == 200
    assert "View past seasons" in resp.text
    assert "/history" in resp.text
