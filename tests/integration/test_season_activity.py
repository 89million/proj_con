"""Regression test for the admin season-activity page on historical seasons."""

import pytest_asyncio

from app.models import Meetup, MeetupRsvp, Season, SeasonParticipant, SeasonState


@pytest_asyncio.fixture
async def completed_season_with_rsvp(db, test_admin, test_user):
    """A completed season with a meetup and one RSVP — mirrors a historical season."""
    season = Season(name="Past Season", state=SeasonState.complete, page_limit=400)
    db.add(season)
    await db.commit()
    await db.refresh(season)
    db.add(SeasonParticipant(season_id=season.id, user_id=test_admin.id))
    db.add(SeasonParticipant(season_id=season.id, user_id=test_user.id))
    from datetime import datetime, timedelta

    meetup = Meetup(season_id=season.id, deadline=datetime.utcnow() + timedelta(days=7))
    db.add(meetup)
    await db.commit()
    await db.refresh(meetup)
    db.add(MeetupRsvp(meetup_id=meetup.id, user_id=test_user.id, status="attending"))
    await db.commit()
    return season


async def test_activity_page_renders_for_historical_season(
    client_as_admin, completed_season_with_rsvp
):
    """The full-activity page must render when a meetup has RSVPs (and some members don't)."""
    resp = await client_as_admin.get(f"/admin/season/{completed_season_with_rsvp.id}/activity")
    assert resp.status_code == 200
    assert "Meetup RSVP" in resp.text
