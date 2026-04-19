"""Integration tests for meetup scheduling/polling."""

import re
from datetime import datetime, timedelta

import pytest_asyncio
from sqlalchemy import func

from app.models import (
    Book,
    BracketMatchup,
    Meetup,
    MeetupOption,
    MeetupRsvp,
    MeetupVote,
    Season,
    SeasonParticipant,
    SeasonState,
)

from .conftest import make_client


@pytest_asyncio.fixture
async def complete_season_with_meetup(db, test_admin, test_user):
    """A completed season with a meetup poll (2 options, deadline 2 weeks out)."""
    season = Season(name="Done Season", state=SeasonState.complete, page_limit=400)
    db.add(season)
    await db.flush()

    # Need participants for notification email queries
    db.add(SeasonParticipant(season_id=season.id, user_id=test_admin.id))
    db.add(SeasonParticipant(season_id=season.id, user_id=test_user.id))

    # Need books + final matchup so get_winner_book_for_season works
    book1 = Book(
        title="Winning Book",
        author="Author A",
        page_count=300,
        submitter_id=test_admin.id,
        season_id=season.id,
    )
    book2 = Book(
        title="Losing Book",
        author="Author B",
        page_count=250,
        submitter_id=test_user.id,
        season_id=season.id,
    )
    db.add_all([book1, book2])
    await db.flush()
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

    deadline = datetime.utcnow() + timedelta(weeks=2)
    meetup = Meetup(season_id=season.id, deadline=deadline)
    db.add(meetup)
    await db.flush()

    opt1 = MeetupOption(
        meetup_id=meetup.id,
        proposed_by=test_admin.id,
        event_datetime=datetime.utcnow() + timedelta(weeks=3),
        location="Monk",
    )
    opt2 = MeetupOption(
        meetup_id=meetup.id,
        proposed_by=test_admin.id,
        event_datetime=datetime.utcnow() + timedelta(weeks=3),
        location="Mixed session",
    )
    db.add_all([opt1, opt2])
    await db.commit()
    await db.refresh(meetup)
    await db.refresh(opt1)
    await db.refresh(opt2)
    return season, meetup, opt1, opt2


# ---------------------------------------------------------------------------
# Page access
# ---------------------------------------------------------------------------


async def test_meetup_page_shows_options(engine, test_user, complete_season_with_meetup):
    """GET /meetup shows the poll with option cards."""
    async with make_client(engine, test_user) as client:
        resp = await client.get("/meetup")
    assert resp.status_code == 200
    assert "Monk" in resp.text
    assert "Mixed session" in resp.text
    assert "Vote for all times that work" in resp.text


async def test_form_action_urls_match_displayed_options(
    engine, db, test_user, test_admin, complete_season_with_meetup
):
    """Form action URLs must contain the ID of the option card they appear in.

    Regression: in-place sort on InstrumentedList caused form actions to point
    to wrong option IDs.
    """
    _, _, opt1, opt2 = complete_season_with_meetup

    # Give opt1 a vote so sorting reorders them (opt1 first, opt2 second)
    db.add(MeetupVote(option_id=opt1.id, user_id=test_admin.id))
    await db.commit()

    async with make_client(engine, test_user) as client:
        resp = await client.get("/meetup")
    html = resp.text

    # Find all vote form actions and the location text in each option card
    # Pattern: each option card has location text and a vote form action
    vote_actions = re.findall(r'action="/meetup/vote/(\d+)"', html)
    # Find all location texts rendered in option cards (the <p class="text-forest-600"> tags)
    locations = re.findall(r'<p class="text-forest-600">\s*([^<]+?)\s*</p>', html)

    # We should have at least 2 options rendered
    assert len(vote_actions) >= 2, f"Expected >=2 vote actions, got {vote_actions}"
    assert len(locations) >= 2, f"Expected >=2 locations, got {locations}"
    assert len(vote_actions) == len(
        locations
    ), f"Mismatch: {len(vote_actions)} actions vs {len(locations)} locations"

    # Build expected mapping: option_id -> location
    id_to_location = {str(opt1.id): "Monk", str(opt2.id): "Mixed session"}

    # Verify each form action ID matches the location displayed in the same card
    for action_id, location in zip(vote_actions, locations):
        expected_location = id_to_location.get(action_id)
        assert expected_location == location.strip(), (
            f"Form action for option {action_id} is next to '{location.strip()}' "
            f"but should be next to '{expected_location}'"
        )


async def test_meetup_page_no_meetup(engine, test_user):
    """GET /meetup with no meetup shows empty state."""
    async with make_client(engine, test_user) as client:
        resp = await client.get("/meetup")
    assert resp.status_code == 200
    assert "No meetup scheduled" in resp.text


# ---------------------------------------------------------------------------
# Adding options
# ---------------------------------------------------------------------------


async def test_add_option(engine, db, test_user, complete_season_with_meetup):
    """POST /meetup/option creates a new option."""
    future = datetime.utcnow() + timedelta(weeks=4)
    async with make_client(engine, test_user) as client:
        resp = await client.post(
            "/meetup/option",
            data={
                "event_month": str(future.month),
                "event_day": str(future.day),
                "event_time": "18:30",
                "location": "The Library",
            },
        )
    assert resp.status_code == 302

    async with make_client(engine, test_user) as client:
        resp = await client.get("/meetup")
    assert "The Library" in resp.text


async def test_add_option_blocked_after_finalization(
    engine, db, test_admin, complete_season_with_meetup
):
    """Cannot add options after the meetup is finalized."""
    _, meetup, opt1, _ = complete_season_with_meetup
    meetup.finalized_option_id = opt1.id
    await db.commit()

    future = datetime.utcnow() + timedelta(weeks=4)
    async with make_client(engine, test_admin) as client:
        resp = await client.post(
            "/meetup/option",
            data={
                "event_month": str(future.month),
                "event_day": str(future.day),
                "event_time": "19:00",
                "location": "New Place",
            },
        )
    assert resp.status_code == 302

    async with make_client(engine, test_admin) as client:
        resp = await client.get("/meetup")
    assert "New Place" not in resp.text


# ---------------------------------------------------------------------------
# Voting
# ---------------------------------------------------------------------------


async def test_vote_toggle_on(engine, db, test_user, complete_season_with_meetup):
    """POST /meetup/vote/{id} adds a vote."""
    _, _, opt1, _ = complete_season_with_meetup
    async with make_client(engine, test_user) as client:
        resp = await client.post(f"/meetup/vote/{opt1.id}")
    assert resp.status_code == 302

    async with make_client(engine, test_user) as client:
        resp = await client.get("/meetup")
    assert "Voted" in resp.text


async def test_vote_toggle_off(engine, db, test_user, complete_season_with_meetup):
    """Voting twice on the same option removes the vote."""
    _, _, opt1, _ = complete_season_with_meetup
    async with make_client(engine, test_user) as client:
        await client.post(f"/meetup/vote/{opt1.id}")
    async with make_client(engine, test_user) as client:
        await client.post(f"/meetup/vote/{opt1.id}")

    # Check no votes remain for this user on this option
    from sqlalchemy import select

    result = await db.execute(
        select(MeetupVote).where(
            MeetupVote.option_id == opt1.id, MeetupVote.user_id == test_user.id
        )
    )
    assert result.scalar_one_or_none() is None


async def test_multi_vote(engine, db, test_user, complete_season_with_meetup):
    """User can vote for multiple options."""
    _, _, opt1, opt2 = complete_season_with_meetup
    async with make_client(engine, test_user) as client:
        await client.post(f"/meetup/vote/{opt1.id}")
    async with make_client(engine, test_user) as client:
        await client.post(f"/meetup/vote/{opt2.id}")

    from sqlalchemy import select

    result = await db.execute(select(MeetupVote).where(MeetupVote.user_id == test_user.id))
    votes = list(result.scalars().all())
    assert len(votes) == 2


async def test_unvote_one_preserves_other(engine, db, test_user, complete_season_with_meetup):
    """Vote for both options, unvote one — the other must survive."""
    _, _, opt1, opt2 = complete_season_with_meetup
    # Vote for both
    async with make_client(engine, test_user) as client:
        await client.post(f"/meetup/vote/{opt1.id}")
    async with make_client(engine, test_user) as client:
        await client.post(f"/meetup/vote/{opt2.id}")

    # Unvote opt1
    async with make_client(engine, test_user) as client:
        await client.post(f"/meetup/vote/{opt1.id}")

    from sqlalchemy import select

    # opt1 vote should be gone
    r1 = await db.execute(
        select(MeetupVote).where(
            MeetupVote.option_id == opt1.id, MeetupVote.user_id == test_user.id
        )
    )
    assert r1.scalar_one_or_none() is None

    # opt2 vote must still exist
    r2 = await db.execute(
        select(MeetupVote).where(
            MeetupVote.option_id == opt2.id, MeetupVote.user_id == test_user.id
        )
    )
    assert r2.scalar_one_or_none() is not None


async def test_repeated_vote_toggle_cycle(engine, db, test_user, complete_season_with_meetup):
    """Rapidly toggling votes across options must never corrupt other votes.

    Reproduces: vote both → unvote A → revote A → unvote B → check A survives.
    """
    _, _, opt1, opt2 = complete_season_with_meetup

    from sqlalchemy import select

    async def vote_counts():
        """Return (opt1_votes, opt2_votes) from the DB via raw connection."""
        # Use raw SQL to bypass ORM identity map / caching
        raw = await db.execute(
            select(MeetupVote.option_id, func.count())
            .where(
                MeetupVote.user_id == test_user.id,
                MeetupVote.option_id.in_([opt1.id, opt2.id]),
            )
            .group_by(MeetupVote.option_id)
        )
        counts = dict(raw.all())
        return counts.get(opt1.id, 0), counts.get(opt2.id, 0)

    async def click(option_id):
        async with make_client(engine, test_user) as client:
            await client.post(f"/meetup/vote/{option_id}")

    # Round 1: vote both
    await click(opt1.id)
    await click(opt2.id)
    assert await vote_counts() == (1, 1), "both should have 1 vote"

    # Round 2: unvote opt1
    await click(opt1.id)
    assert await vote_counts() == (0, 1), "opt1 removed, opt2 untouched"

    # Round 3: revote opt1
    await click(opt1.id)
    assert await vote_counts() == (1, 1), "both should have 1 vote again"

    # Round 4: unvote opt2
    await click(opt2.id)
    assert await vote_counts() == (1, 0), "opt2 removed, opt1 untouched"

    # Round 5: unvote opt1
    await click(opt1.id)
    assert await vote_counts() == (0, 0), "both removed"

    # Round 6: vote both again from scratch
    await click(opt1.id)
    await click(opt2.id)
    assert await vote_counts() == (1, 1), "both should have 1 vote from scratch"


async def test_vote_blocked_after_finalization(engine, db, test_user, complete_season_with_meetup):
    """Cannot vote after meetup is finalized."""
    _, meetup, opt1, opt2 = complete_season_with_meetup
    meetup.finalized_option_id = opt1.id
    await db.commit()

    async with make_client(engine, test_user) as client:
        await client.post(f"/meetup/vote/{opt2.id}")

    from sqlalchemy import select

    result = await db.execute(select(MeetupVote).where(MeetupVote.user_id == test_user.id))
    assert result.scalar_one_or_none() is None


# ---------------------------------------------------------------------------
# Delete option
# ---------------------------------------------------------------------------


async def test_delete_own_option(engine, db, test_user, complete_season_with_meetup):
    """User can delete their own option if no others voted on it."""
    _, meetup, _, _ = complete_season_with_meetup
    # Create an option by the test user
    opt = MeetupOption(
        meetup_id=meetup.id,
        proposed_by=test_user.id,
        event_datetime=datetime.utcnow() + timedelta(weeks=4),
        location="My Place",
    )
    db.add(opt)
    await db.commit()
    await db.refresh(opt)

    async with make_client(engine, test_user) as client:
        resp = await client.post(f"/meetup/option/{opt.id}/delete")
    assert resp.status_code == 302

    async with make_client(engine, test_user) as client:
        resp = await client.get("/meetup")
    assert "My Place" not in resp.text


async def test_delete_blocked_with_other_votes(
    engine, db, test_user, extra_user, complete_season_with_meetup
):
    """Cannot delete option if another user voted on it."""
    _, meetup, _, _ = complete_season_with_meetup
    opt = MeetupOption(
        meetup_id=meetup.id,
        proposed_by=test_user.id,
        event_datetime=datetime.utcnow() + timedelta(weeks=4),
        location="My Place",
    )
    db.add(opt)
    await db.flush()
    db.add(MeetupVote(option_id=opt.id, user_id=extra_user.id))
    await db.commit()
    await db.refresh(opt)

    async with make_client(engine, test_user) as client:
        await client.post(f"/meetup/option/{opt.id}/delete")

    async with make_client(engine, test_user) as client:
        resp = await client.get("/meetup")
    assert "My Place" in resp.text


# ---------------------------------------------------------------------------
# Admin controls
# ---------------------------------------------------------------------------


async def test_admin_finalize(engine, db, test_admin, complete_season_with_meetup):
    """Admin can manually finalize the meetup."""
    _, _, opt1, _ = complete_season_with_meetup
    async with make_client(engine, test_admin) as client:
        resp = await client.post("/meetup/finalize", data={"option_id": str(opt1.id)})
    assert resp.status_code == 302

    async with make_client(engine, test_admin) as client:
        resp = await client.get("/meetup")
    assert "Meetup Scheduled!" in resp.text
    assert "Monk" in resp.text


async def test_admin_update_deadline(engine, db, test_admin, complete_season_with_meetup):
    """Admin can update the voting deadline."""
    future = datetime.utcnow() + timedelta(weeks=4)
    async with make_client(engine, test_admin) as client:
        resp = await client.post(
            "/meetup/deadline",
            data={
                "deadline_date": future.strftime("%Y-%m-%d"),
                "deadline_time": "23:59",
            },
        )
    assert resp.status_code == 302


# ---------------------------------------------------------------------------
# Reactive finalization
# ---------------------------------------------------------------------------


async def test_reactive_finalization_on_page_load(
    engine, db, test_user, test_admin, complete_season_with_meetup
):
    """When deadline has passed, loading the page auto-finalizes with top-voted option."""
    _, meetup, opt1, opt2 = complete_season_with_meetup

    # Vote: opt1 gets 2 votes, opt2 gets 1
    db.add(MeetupVote(option_id=opt1.id, user_id=test_user.id))
    db.add(MeetupVote(option_id=opt1.id, user_id=test_admin.id))
    db.add(MeetupVote(option_id=opt2.id, user_id=test_user.id))
    meetup.deadline = datetime.utcnow() - timedelta(hours=1)
    await db.commit()

    async with make_client(engine, test_user) as client:
        resp = await client.get("/meetup")
    assert "Meetup Scheduled!" in resp.text
    assert "Monk" in resp.text  # opt1 (Monk) had more votes


async def test_finalized_meetup_shows_all_results(
    engine, db, test_user, complete_season_with_meetup
):
    """Finalized view shows all options with vote counts."""
    _, meetup, opt1, _ = complete_season_with_meetup
    meetup.finalized_option_id = opt1.id
    await db.commit()

    async with make_client(engine, test_user) as client:
        resp = await client.get("/meetup")
    assert "Meetup Scheduled!" in resp.text
    assert "All Options" in resp.text
    assert "Monk" in resp.text
    assert "Mixed session" in resp.text


# ---------------------------------------------------------------------------
# Complete page CTA
# ---------------------------------------------------------------------------


async def test_complete_page_shows_meetup_cta(engine, test_user, complete_season_with_meetup):
    """The /complete page shows a 'Vote on meetup time' button when meetup is open."""
    async with make_client(engine, test_user) as client:
        resp = await client.get("/complete")
    assert resp.status_code == 200
    assert "Vote on meetup time" in resp.text


async def test_complete_page_shows_rsvp_cta_when_finalized(engine, test_user, finalized_meetup):
    """The /complete page shows 'RSVP for meetup' once voting is closed."""
    async with make_client(engine, test_user) as client:
        resp = await client.get("/complete")
    assert resp.status_code == 200
    assert "RSVP for meetup" in resp.text
    assert "Vote on meetup time" not in resp.text


# ---------------------------------------------------------------------------
# RSVP
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def finalized_meetup(db, complete_season_with_meetup):
    """Returns a meetup finalized on opt1."""
    _, meetup, opt1, _ = complete_season_with_meetup
    meetup.finalized_option_id = opt1.id
    await db.commit()
    return meetup, opt1


async def test_rsvp_submit_attending(engine, db, test_user, finalized_meetup):
    """POST /meetup/rsvp saves an attending RSVP with in_person venue."""
    meetup, _ = finalized_meetup
    async with make_client(engine, test_user) as client:
        resp = await client.post(
            "/meetup/rsvp",
            data={"status": "attending", "venue": "in_person"},
        )
    assert resp.status_code == 302

    from sqlalchemy import select as sa_select

    result = await db.execute(
        sa_select(MeetupRsvp).where(
            MeetupRsvp.meetup_id == meetup.id,
            MeetupRsvp.user_id == test_user.id,
        )
    )
    rsvp = result.scalar_one()
    assert rsvp.status == "attending"
    assert rsvp.venue == "in_person"
    assert rsvp.discord_ok is None


async def test_rsvp_remote_with_discord(engine, db, test_user, finalized_meetup):
    """Remote RSVP with discord_ok=True is stored correctly."""
    meetup, _ = finalized_meetup
    async with make_client(engine, test_user) as client:
        await client.post(
            "/meetup/rsvp",
            data={"status": "attending", "venue": "remote", "discord_ok": "true"},
        )

    from sqlalchemy import select as sa_select

    result = await db.execute(sa_select(MeetupRsvp).where(MeetupRsvp.meetup_id == meetup.id))
    rsvp = result.scalar_one()
    assert rsvp.venue == "remote"
    assert rsvp.discord_ok is True


async def test_rsvp_not_attending_clears_venue(engine, db, test_user, finalized_meetup):
    """not_attending status stores no venue even if one is passed."""
    meetup, _ = finalized_meetup
    async with make_client(engine, test_user) as client:
        await client.post(
            "/meetup/rsvp",
            data={"status": "not_attending", "venue": "in_person"},
        )

    from sqlalchemy import select as sa_select

    result = await db.execute(sa_select(MeetupRsvp).where(MeetupRsvp.meetup_id == meetup.id))
    rsvp = result.scalar_one()
    assert rsvp.status == "not_attending"
    assert rsvp.venue is None
    assert rsvp.discord_ok is None


async def test_rsvp_update_overwrites_previous(engine, db, test_user, finalized_meetup):
    """Submitting RSVP twice updates the existing row (upsert)."""
    meetup, _ = finalized_meetup
    async with make_client(engine, test_user) as client:
        await client.post("/meetup/rsvp", data={"status": "attending", "venue": "in_person"})
        await client.post("/meetup/rsvp", data={"status": "not_attending"})

    from sqlalchemy import func as sa_func
    from sqlalchemy import select as sa_select

    count = await db.scalar(sa_select(sa_func.count()).where(MeetupRsvp.meetup_id == meetup.id))
    assert count == 1

    result = await db.execute(sa_select(MeetupRsvp).where(MeetupRsvp.meetup_id == meetup.id))
    rsvp = result.scalar_one()
    assert rsvp.status == "not_attending"


async def test_rsvp_rejected_on_unfinalized_meetup(engine, test_user, complete_season_with_meetup):
    """POST /meetup/rsvp on an unfinalized meetup redirects without saving."""
    async with make_client(engine, test_user) as client:
        resp = await client.post("/meetup/rsvp", data={"status": "attending", "venue": "in_person"})
    assert resp.status_code == 302


async def test_rsvp_summary_shown_on_meetup_page(
    engine, db, test_user, test_admin, finalized_meetup
):
    """Finalized meetup page shows RSVP summary with attendee names."""
    meetup, _ = finalized_meetup
    db.add(
        MeetupRsvp(meetup_id=meetup.id, user_id=test_user.id, status="attending", venue="in_person")
    )
    db.add(MeetupRsvp(meetup_id=meetup.id, user_id=test_admin.id, status="not_attending"))
    await db.commit()

    async with make_client(engine, test_user) as client:
        resp = await client.get("/meetup")
    assert resp.status_code == 200
    assert "Coming" in resp.text
    assert "Can't make it" in resp.text
    assert "in person" in resp.text


async def test_rsvp_maybe_with_remote_discord(engine, db, test_user, finalized_meetup):
    """maybe status with remote venue and discord is stored and displayed."""
    meetup, _ = finalized_meetup
    async with make_client(engine, test_user) as client:
        await client.post(
            "/meetup/rsvp",
            data={"status": "maybe", "venue": "remote", "discord_ok": "true"},
        )

    from sqlalchemy import select as sa_select

    result = await db.execute(sa_select(MeetupRsvp).where(MeetupRsvp.meetup_id == meetup.id))
    rsvp = result.scalar_one()
    assert rsvp.status == "maybe"
    assert rsvp.venue == "remote"
    assert rsvp.discord_ok is True


async def test_rsvp_invalid_status_ignored(engine, db, test_user, finalized_meetup):
    """An invalid status value redirects without creating a row."""
    meetup, _ = finalized_meetup
    async with make_client(engine, test_user) as client:
        resp = await client.post("/meetup/rsvp", data={"status": "yes_definitely"})
    assert resp.status_code == 302

    from sqlalchemy import func as sa_func
    from sqlalchemy import select as sa_select

    count = await db.scalar(sa_select(sa_func.count()).where(MeetupRsvp.meetup_id == meetup.id))
    assert count == 0


# ---------------------------------------------------------------------------
# Admin option update (location + is_hybrid)
# ---------------------------------------------------------------------------


async def test_admin_can_update_location(engine, db, test_admin, finalized_meetup):
    """Admin can update the finalized option's location."""
    meetup, opt1 = finalized_meetup
    async with make_client(engine, test_admin) as client:
        resp = await client.post(
            f"/admin/meetup/option/{opt1.id}",
            data={"location": "Chris's place — 42 Elm St", "is_hybrid": ""},
        )
    assert resp.status_code == 302

    await db.refresh(opt1)
    assert opt1.location == "Chris's place — 42 Elm St"
    assert opt1.is_hybrid is False


async def test_admin_can_set_hybrid(engine, db, test_admin, finalized_meetup):
    """Admin can mark the finalized option as hybrid."""
    meetup, opt1 = finalized_meetup
    async with make_client(engine, test_admin) as client:
        await client.post(
            f"/admin/meetup/option/{opt1.id}",
            data={"location": "Hybrid — Library + Discord", "is_hybrid": "true"},
        )

    await db.refresh(opt1)
    assert opt1.is_hybrid is True


async def test_only_finalized_option_url_accepted(engine, db, test_admin, finalized_meetup):
    """Update is rejected (redirect) when URL option_id is not the finalized option."""
    meetup, opt1 = finalized_meetup
    wrong_id = opt1.id + 999
    async with make_client(engine, test_admin) as client:
        resp = await client.post(
            f"/admin/meetup/option/{wrong_id}",
            data={"location": "Sneaky change", "is_hybrid": ""},
        )
    assert resp.status_code == 302
    await db.refresh(opt1)
    assert opt1.location == "Monk"


async def test_admin_cannot_update_non_finalized_option(
    engine, db, test_admin, complete_season_with_meetup
):
    """Admin update is rejected if the option isn't the finalized one."""
    _, meetup, opt1, opt2 = complete_season_with_meetup
    meetup.finalized_option_id = opt1.id
    await db.commit()

    async with make_client(engine, test_admin) as client:
        resp = await client.post(
            f"/admin/meetup/option/{opt2.id}",
            data={"location": "Wrong option", "is_hybrid": ""},
        )
    assert resp.status_code == 302

    from sqlalchemy import select as sa_select

    result = await db.execute(sa_select(MeetupOption).where(MeetupOption.id == opt2.id))
    opt = result.scalar_one()
    assert opt.location == "Mixed session"


async def test_hybrid_flag_controls_venue_section_in_page(engine, db, test_admin, finalized_meetup):
    """IS_HYBRID JS var is true only when is_hybrid is set on the finalized option."""
    meetup, opt1 = finalized_meetup

    async with make_client(engine, test_admin) as client:
        resp = await client.get("/meetup")
    assert "IS_HYBRID = false" in resp.text

    opt1.is_hybrid = True
    await db.commit()

    async with make_client(engine, test_admin) as client:
        resp = await client.get("/meetup")
    assert "IS_HYBRID = true" in resp.text
