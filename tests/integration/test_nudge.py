"""Integration tests for the nudge button feature."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest_asyncio

from app.models import Book, Season, SeasonParticipant, SeasonState


@pytest_asyncio.fixture
async def submit_season(db, test_admin, test_user):
    """A season in submit state with both users as participants, only admin has submitted."""
    season = Season(name="Nudge Test", state=SeasonState.submit, page_limit=400)
    db.add(season)
    await db.commit()
    await db.refresh(season)

    db.add(SeasonParticipant(season_id=season.id, user_id=test_admin.id))
    db.add(SeasonParticipant(season_id=season.id, user_id=test_user.id))

    # Only admin submits
    db.add(
        Book(
            title="Admin Book",
            author="Author A",
            page_count=200,
            submitter_id=test_admin.id,
            season_id=season.id,
        )
    )
    await db.commit()
    await db.refresh(season)
    return season


async def test_nudge_sends_to_stragglers(client_as_admin, submit_season, db, test_admin):
    """Nudging sends notifications to users who haven't submitted."""
    with patch("app.notify.notify_all", new_callable=AsyncMock) as mock_notify:
        resp = await client_as_admin.post(f"/admin/season/{submit_season.id}/nudge")
    assert resp.status_code == 302
    mock_notify.assert_called_once()
    # The Discord message should mention "submit"
    call_kwargs = mock_notify.call_args
    assert "submit" in call_kwargs.kwargs.get(
        "discord_msg", call_kwargs.args[1] if len(call_kwargs.args) > 1 else ""
    )


async def test_nudge_cooldown(client_as_admin, submit_season, db):
    """Second nudge within cooldown is rejected."""
    # Set last_nudge_at to 5 minutes ago
    submit_season.last_nudge_at = datetime.utcnow() - timedelta(minutes=5)
    await db.commit()

    resp = await client_as_admin.post(
        f"/admin/season/{submit_season.id}/nudge",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "nudge=cooldown" in resp.headers.get("location", "")


async def test_nudge_no_stragglers(client_as_admin, db, test_admin, test_user):
    """When everyone has submitted, nudge is a no-op (no notifications sent)."""
    season = Season(name="All Done", state=SeasonState.submit, page_limit=400)
    db.add(season)
    await db.commit()
    await db.refresh(season)

    db.add(SeasonParticipant(season_id=season.id, user_id=test_admin.id))
    db.add(SeasonParticipant(season_id=season.id, user_id=test_user.id))

    for user in [test_admin, test_user]:
        db.add(
            Book(
                title=f"Book by {user.name}",
                author="Auth",
                page_count=200,
                submitter_id=user.id,
                season_id=season.id,
            )
        )
    await db.commit()

    with patch("app.notify.send_nudge", new_callable=AsyncMock) as mock_nudge:
        resp = await client_as_admin.post(f"/admin/season/{season.id}/nudge")
    assert resp.status_code == 302
    mock_nudge.assert_not_called()
