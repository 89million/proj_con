"""Integration tests for the root route (/) routing logic.

Covers:
- Unauthenticated user → landing page
- Active season in each state → redirect to the right page
- No active season, completed season exists → /complete (covered in test_complete_and_history.py)
- No seasons at all → no_season.html (covered in test_complete_and_history.py)
"""

import pytest_asyncio

from app.models import Season, SeasonParticipant, SeasonState

from .conftest import make_client

# ---------------------------------------------------------------------------
# Local fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def submit_season(db, test_admin, test_user):
    """Active season in submit state with both users enrolled."""
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
    """Active season in ranking state."""
    season = Season(name="Ranking Season", state=SeasonState.ranking, page_limit=400)
    db.add(season)
    await db.commit()
    await db.refresh(season)
    db.add(SeasonParticipant(season_id=season.id, user_id=test_admin.id))
    db.add(SeasonParticipant(season_id=season.id, user_id=test_user.id))
    await db.commit()
    return season


@pytest_asyncio.fixture
async def bracket_season(db, test_admin, test_user):
    """Active season in bracket state."""
    season = Season(name="Bracket Season", state=SeasonState.bracket, page_limit=400)
    db.add(season)
    await db.commit()
    await db.refresh(season)
    db.add(SeasonParticipant(season_id=season.id, user_id=test_admin.id))
    db.add(SeasonParticipant(season_id=season.id, user_id=test_user.id))
    await db.commit()
    return season


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_root_unauthenticated_shows_landing(engine, db):
    """A visitor with no session (user=None) sees the landing page."""
    async with make_client(engine, None) as client:
        resp = await client.get("/", follow_redirects=True)
    assert resp.status_code == 200
    assert "Sign in with Google" in resp.text


async def test_root_redirects_to_submit_when_submit_state(engine, test_user, submit_season):
    """Logged-in user is sent to /submit when the active season is in submit state."""
    async with make_client(engine, test_user) as client:
        resp = await client.get("/", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/submit"


async def test_root_redirects_to_ranking_when_ranking_state(engine, test_user, ranking_season):
    """Logged-in user is sent to /ranking when the active season is in ranking state."""
    async with make_client(engine, test_user) as client:
        resp = await client.get("/", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/ranking"


async def test_root_redirects_to_bracket_when_bracket_state(engine, test_user, bracket_season):
    """Logged-in user is sent to /bracket when the active season is in bracket state."""
    async with make_client(engine, test_user) as client:
        resp = await client.get("/", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/bracket"
