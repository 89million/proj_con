"""Integration tests for the complete/winner page and history routes."""

import pytest_asyncio

from app.models import Book, BracketMatchup, Season, SeasonState

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
