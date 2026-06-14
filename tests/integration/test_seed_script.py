"""Smoke tests for the demo-seed script's stage-driving logic.

`_drive` takes the session as a parameter, so we can exercise the full
orchestration against the in-memory test DB without a real Postgres.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app import crud
from app.models import SeasonState
from scripts import seed_demo


async def _make_users(db, n):
    return [await crud.create_user(db, f"Demo {i}", f"demo{i}@seed.local") for i in range(1, n + 1)]


@pytest.mark.parametrize(
    "stage,expected_state",
    [
        ("submit", SeasonState.submit),
        ("ranking", SeasonState.ranking),
        ("bracket", SeasonState.bracket),
        ("complete", SeasonState.complete),
    ],
)
async def test_drive_reaches_target_stage(db, stage, expected_state):
    users = await _make_users(db, 4)
    season = await crud.create_season(db, f"Demo {stage}", 2000)
    for u in users:
        await crud.add_participant(db, season.id, u.id)

    # Don't hit OpenLibrary during the drive.
    with patch.object(seed_demo, "fetch_cover_url", new=AsyncMock(return_value=None)):
        await seed_demo._drive(db, season, users, stage)

    await db.refresh(season)
    assert season.state == expected_state


async def test_drive_submit_leaves_one_straggler(db):
    """In `submit` stage, one user is intentionally left without a book."""
    users = await _make_users(db, 4)
    season = await crud.create_season(db, "Demo straggler", 2000)
    for u in users:
        await crud.add_participant(db, season.id, u.id)

    with patch.object(seed_demo, "fetch_cover_url", new=AsyncMock(return_value=None)):
        await seed_demo._drive(db, season, users, "submit")

    books = await crud.get_books_for_season(db, season.id)
    assert len(books) == len(users) - 1  # exactly one straggler remains
