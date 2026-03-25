"""Integration tests for per-season participation (opt-out and admin management)."""

import pytest_asyncio
from sqlalchemy import select

from app.models import Book, Season, SeasonParticipant, SeasonState

from .conftest import make_client

# ---------------------------------------------------------------------------
# Helpers / local fixtures
# ---------------------------------------------------------------------------


async def _participant_ids(db, season_id: int) -> set[int]:
    result = await db.execute(
        select(SeasonParticipant.user_id).where(SeasonParticipant.season_id == season_id)
    )
    return {row[0] for row in result.all()}


@pytest_asyncio.fixture
async def season_with_one_participant(db, test_admin):
    """Season with only test_admin enrolled (1 participant)."""
    season = Season(name="Solo Season", state=SeasonState.submit, page_limit=400)
    db.add(season)
    await db.commit()
    await db.refresh(season)
    db.add(SeasonParticipant(season_id=season.id, user_id=test_admin.id))
    await db.commit()
    return season


# ---------------------------------------------------------------------------
# Season creation auto-enroll
# ---------------------------------------------------------------------------


async def test_create_season_auto_enrolls_all_users(client_as_admin, test_admin, test_user, db):
    """Creating a season via the admin route auto-enrolls every existing user."""
    resp = await client_as_admin.post(
        "/admin/season", data={"name": "New Season", "page_limit": "300"}
    )
    assert resp.status_code == 302

    result = await db.execute(select(Season).where(Season.name == "New Season"))
    season = result.scalar_one()

    enrolled = await _participant_ids(db, season.id)
    assert test_admin.id in enrolled
    assert test_user.id in enrolled


# ---------------------------------------------------------------------------
# Opt-out (POST /submit/opt-out)
# ---------------------------------------------------------------------------


async def test_opt_out_removes_participant(client_as_user, active_season, db, test_user):
    """A user who hasn't submitted can opt out and is removed from participants."""
    assert test_user.id in await _participant_ids(db, active_season.id)

    resp = await client_as_user.post("/submit/opt-out")
    assert resp.status_code == 302

    assert test_user.id not in await _participant_ids(db, active_season.id)


async def test_opt_out_blocked_after_submission(client_as_user, active_season, db, test_user):
    """A user who already submitted a book cannot opt out."""
    db.add(
        Book(
            title="My Book",
            author="Me",
            page_count=200,
            submitter_id=test_user.id,
            season_id=active_season.id,
        )
    )
    await db.commit()

    resp = await client_as_user.post("/submit/opt-out")
    # Redirects to /submit (not /), and participant row is preserved
    assert resp.status_code == 302
    assert resp.headers["location"] == "/submit"
    assert test_user.id in await _participant_ids(db, active_season.id)


async def test_opt_out_redirects_to_home_outside_submit(client_as_user, active_season, db):
    """Opt-out is a no-op when the season is not in submit state."""
    active_season.state = SeasonState.ranking
    await db.commit()

    resp = await client_as_user.post("/submit/opt-out")
    assert resp.status_code == 302
    assert resp.headers["location"] == "/"


async def test_opt_out_advances_season_when_last_blocker_leaves(
    client_as_user, active_season, db, test_admin, test_user
):
    """Opting out while everyone else has already submitted triggers phase advance."""
    # test_admin has submitted; test_user hasn't — test_user is the only blocker
    db.add(
        Book(
            title="Admin Book",
            author="Auth",
            page_count=200,
            submitter_id=test_admin.id,
            season_id=active_season.id,
        )
    )
    await db.commit()

    resp = await client_as_user.post("/submit/opt-out")
    assert resp.status_code == 302

    await db.refresh(active_season)
    assert active_season.state == SeasonState.ranking


# ---------------------------------------------------------------------------
# Admin participant management
# ---------------------------------------------------------------------------


async def test_admin_remove_participant(client_as_admin, active_season, db, test_user):
    """Admin can remove a participant from an active season."""
    assert test_user.id in await _participant_ids(db, active_season.id)

    resp = await client_as_admin.post(
        f"/admin/season/{active_season.id}/participants/remove/{test_user.id}"
    )
    assert resp.status_code == 302

    assert test_user.id not in await _participant_ids(db, active_season.id)


async def test_admin_add_participant(client_as_admin, active_season, extra_user, db):
    """Admin can add a non-enrolled user as a participant."""
    assert extra_user.id not in await _participant_ids(db, active_season.id)

    resp = await client_as_admin.post(
        f"/admin/season/{active_season.id}/participants/add",
        data={"user_id": str(extra_user.id)},
    )
    assert resp.status_code == 302

    assert extra_user.id in await _participant_ids(db, active_season.id)


async def test_admin_add_participant_idempotent(client_as_admin, active_season, test_user, db):
    """Adding an already-enrolled participant does not raise an error."""
    assert test_user.id in await _participant_ids(db, active_season.id)

    resp = await client_as_admin.post(
        f"/admin/season/{active_season.id}/participants/add",
        data={"user_id": str(test_user.id)},
    )
    assert resp.status_code == 302

    # Still exactly one enrollment row for this user
    result = await db.execute(
        select(SeasonParticipant).where(
            SeasonParticipant.season_id == active_season.id,
            SeasonParticipant.user_id == test_user.id,
        )
    )
    assert len(result.scalars().all()) == 1


async def test_admin_remove_advances_season(
    client_as_admin, season_with_one_participant, test_admin, db, test_user
):
    """Removing the only non-submitter unblocks phase advance."""
    season = season_with_one_participant
    # Enroll test_user as a second participant (the blocker), and have test_admin submit
    db.add(SeasonParticipant(season_id=season.id, user_id=test_user.id))
    db.add(
        Book(
            title="Admin Book",
            author="Auth",
            page_count=200,
            submitter_id=test_admin.id,
            season_id=season.id,
        )
    )
    await db.commit()

    # Remove test_user — test_admin is now the only participant and has already submitted
    resp = await client_as_admin.post(
        f"/admin/season/{season.id}/participants/remove/{test_user.id}"
    )
    assert resp.status_code == 302

    await db.refresh(season)
    assert season.state == SeasonState.ranking


# ---------------------------------------------------------------------------
# Spectator mode (opted-out user sees read-only pages)
# ---------------------------------------------------------------------------


async def test_spectator_sees_banner_on_submit_page(
    engine, db, test_user, test_admin, active_season
):
    """An opted-out user sees the spectator banner instead of the submission form."""
    await db.execute(
        select(SeasonParticipant).where(
            SeasonParticipant.season_id == active_season.id,
            SeasonParticipant.user_id == test_user.id,
        )
    )
    from app import crud

    await crud.remove_participant(db, active_season.id, test_user.id)

    async with make_client(engine, test_user) as client:
        resp = await client.get("/submit")
    assert resp.status_code == 200
    assert "spectating" in resp.text.lower()
    assert "Submit Book" not in resp.text


async def test_spectator_cannot_post_submission(engine, db, test_user, test_admin, active_season):
    """An opted-out user's POST to /submit is rejected."""
    from app import crud

    await crud.remove_participant(db, active_season.id, test_user.id)

    async with make_client(engine, test_user) as client:
        resp = await client.post(
            "/submit",
            data={"title": "Sneaky Book", "author": "Hacker", "page_count": 100},
        )
    assert resp.status_code == 302

    result = await db.execute(select(Book).where(Book.title == "Sneaky Book"))
    assert result.scalar_one_or_none() is None


async def test_spectator_can_still_see_submissions(
    engine, db, test_user, test_admin, active_season
):
    """An opted-out user can see others' submissions on the submit page."""
    from app import crud

    # Admin submits a book
    db.add(
        Book(
            title="Admin Book",
            author="Admin",
            page_count=200,
            submitter_id=test_admin.id,
            season_id=active_season.id,
        )
    )
    await db.commit()

    await crud.remove_participant(db, active_season.id, test_user.id)

    async with make_client(engine, test_user) as client:
        resp = await client.get("/submit")
    assert resp.status_code == 200
    assert "Admin Book" in resp.text
