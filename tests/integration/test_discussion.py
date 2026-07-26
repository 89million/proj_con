"""Integration tests for the page-anchored discussion on the complete page.

The property worth guarding is that a post the reader hasn't reached never has
its real text rendered into the response — not hidden with CSS, actually absent.
"""

import pytest_asyncio
from sqlalchemy import select

from app.models import (
    Book,
    BracketMatchup,
    DiscussionPost,
    ReadingProgress,
    Season,
    SeasonParticipant,
    SeasonState,
)

from .conftest import make_client

# Distinctive words so a leak is unambiguous when asserting on the response.
LATE_BODY = "Elizabeth is murdered on the wedding night and Victor finally understands everything"
EARLY_BODY = "Walton's opening letters set up the whole tragedy before it starts"


@pytest_asyncio.fixture
async def complete_season(db, test_admin, test_user):
    """A completed season whose winner is a 300-page book."""
    season = Season(name="Fog Season", state=SeasonState.complete, page_limit=400)
    db.add(season)
    await db.flush()

    db.add(SeasonParticipant(season_id=season.id, user_id=test_admin.id))
    db.add(SeasonParticipant(season_id=season.id, user_id=test_user.id))

    winner = Book(
        title="Winning Book",
        author="Author A",
        page_count=300,
        submitter_id=test_admin.id,
        season_id=season.id,
    )
    loser = Book(
        title="Losing Book",
        author="Author B",
        page_count=250,
        submitter_id=test_user.id,
        season_id=season.id,
    )
    db.add_all([winner, loser])
    await db.flush()
    db.add(
        BracketMatchup(
            season_id=season.id,
            round=1,
            position=1,
            book_a_id=winner.id,
            book_b_id=loser.id,
            winner_id=winner.id,
        )
    )
    await db.commit()
    await db.refresh(season)
    return season


async def _set_progress(db, season, user, percent):
    db.add(ReadingProgress(season_id=season.id, user_id=user.id, percent=percent))
    await db.commit()


async def _add_post(db, season, user, anchor_page, body):
    post = DiscussionPost(season_id=season.id, user_id=user.id, anchor_page=anchor_page, body=body)
    db.add(post)
    await db.commit()
    await db.refresh(post)
    return post


# ---------------------------------------------------------------------------
# Posting
# ---------------------------------------------------------------------------


async def test_posting_stores_body_and_anchor(engine, db, test_user, complete_season):
    async with make_client(engine, test_user) as client:
        resp = await client.post("/discussion", data={"body": "Great opening", "anchor_page": "42"})

    assert resp.status_code == 302
    assert resp.headers["location"] == "/complete#discussion"

    post = (await db.execute(select(DiscussionPost))).scalar_one()
    assert post.body == "Great opening"
    assert post.anchor_page == 42
    assert post.user_id == test_user.id


async def test_anchor_is_clamped_to_the_books_length(engine, db, test_user, complete_season):
    async with make_client(engine, test_user) as client:
        await client.post("/discussion", data={"body": "Way past the end", "anchor_page": "9999"})

    post = (await db.execute(select(DiscussionPost))).scalar_one()
    assert post.anchor_page == 300


async def test_blank_body_is_rejected(engine, db, test_user, complete_season):
    async with make_client(engine, test_user) as client:
        await client.post("/discussion", data={"body": "   ", "anchor_page": "10"})

    assert (await db.execute(select(DiscussionPost))).first() is None


async def test_reply_inherits_the_parents_anchor(
    engine, db, test_user, test_admin, complete_season
):
    parent = await _add_post(db, complete_season, test_admin, 250, LATE_BODY)

    async with make_client(engine, test_user) as client:
        await client.post(f"/discussion/{parent.id}/reply", data={"body": "Agreed entirely"})

    reply = (
        await db.execute(select(DiscussionPost).where(DiscussionPost.parent_id == parent.id))
    ).scalar_one()
    assert reply.anchor_page == 250, "a reply must not be visible before the post it answers"


# ---------------------------------------------------------------------------
# The leak test
# ---------------------------------------------------------------------------


async def test_far_ahead_post_is_absent_from_the_response(
    engine, db, test_user, test_admin, complete_season
):
    """A reader at page 30 must not receive the words of a post about page 280."""
    await _add_post(db, complete_season, test_admin, 280, LATE_BODY)
    await _set_progress(db, complete_season, test_user, 10)  # 10% of 300 = p.30

    async with make_client(engine, test_user) as client:
        html = (await client.get("/complete")).text

    for word in ("Elizabeth", "murdered", "wedding", "Victor"):
        assert word not in html, f"{word!r} leaked into the page"


async def test_reader_who_arrived_sees_the_real_text(
    engine, db, test_user, test_admin, complete_season
):
    await _add_post(db, complete_season, test_admin, 280, LATE_BODY)
    await _set_progress(db, complete_season, test_user, 100)

    async with make_client(engine, test_user) as client:
        html = (await client.get("/complete")).text

    assert "Elizabeth" in html
    assert "murdered" in html


async def test_earlier_posts_stay_readable(engine, db, test_user, test_admin, complete_season):
    """Fog applies per post — an early post is unaffected by a later one."""
    await _add_post(db, complete_season, test_admin, 5, EARLY_BODY)
    await _add_post(db, complete_season, test_admin, 280, LATE_BODY)
    await _set_progress(db, complete_season, test_user, 30)  # p.90

    async with make_client(engine, test_user) as client:
        html = (await client.get("/complete")).text

    assert "tragedy" in html
    assert "Elizabeth" not in html


async def test_where_a_post_sits_in_the_book_makes_no_difference(
    engine, db, test_user, test_admin, complete_season
):
    """Only distance matters. A mid-book post ahead of you is scrambled too."""
    await _add_post(db, complete_season, test_admin, 150, EARLY_BODY)  # p.150 of 300
    await _set_progress(db, complete_season, test_user, 0)

    async with make_client(engine, test_user) as client:
        html = (await client.get("/complete")).text

    assert EARLY_BODY not in html
    # Words distinctive enough that they can't collide with page furniture —
    # a plain word like "letters" also appears in the template's own comments.
    for word in ("Walton's", "tragedy"):
        assert word not in html, f"{word!r} leaked from a mid-book post"


async def test_the_ending_is_still_hidden_from_a_mid_book_reader(
    engine, db, test_user, test_admin, complete_season
):
    """Opening up the middle must not open up the last pages."""
    await _add_post(db, complete_season, test_admin, 295, LATE_BODY)  # p.295 of 300
    await _set_progress(db, complete_season, test_user, 50)  # p.150

    async with make_client(engine, test_user) as client:
        html = (await client.get("/complete")).text

    for word in ("Elizabeth", "murdered", "wedding"):
        assert word not in html, f"{word!r} leaked from the ending"


async def test_your_own_post_is_never_fogged_to_you(engine, db, test_user, complete_season):
    """Posting ahead of where you are shouldn't hide your own words from you."""
    await _add_post(db, complete_season, test_user, 290, LATE_BODY)
    await _set_progress(db, complete_season, test_user, 0)

    async with make_client(engine, test_user) as client:
        html = (await client.get("/complete")).text

    assert "Elizabeth" in html


async def test_someone_elses_reply_is_fogged_on_your_own_thread(
    engine, db, test_user, test_admin, complete_season
):
    """Seeing your own far-ahead post must not expose replies to it."""
    parent = await _add_post(db, complete_season, test_user, 290, "What did everyone think here")
    db.add(
        DiscussionPost(
            season_id=complete_season.id,
            user_id=test_admin.id,
            parent_id=parent.id,
            anchor_page=290,
            body=LATE_BODY,
        )
    )
    await db.commit()
    await _set_progress(db, complete_season, test_user, 0)

    async with make_client(engine, test_user) as client:
        html = (await client.get("/complete")).text

    assert "What did everyone think here" in html, "your own post should still be readable"
    assert "Elizabeth" not in html, "another member's reply leaked"


# ---------------------------------------------------------------------------
# Deletion
# ---------------------------------------------------------------------------


async def test_author_can_delete_their_post(engine, db, test_user, complete_season):
    post = await _add_post(db, complete_season, test_user, 10, "Never mind")

    async with make_client(engine, test_user) as client:
        await client.post(f"/discussion/{post.id}/delete")

    assert (await db.execute(select(DiscussionPost))).first() is None


async def test_member_cannot_delete_someone_elses_post(
    engine, db, test_user, test_admin, complete_season
):
    post = await _add_post(db, complete_season, test_admin, 10, "Mine, not yours")

    async with make_client(engine, test_user) as client:
        await client.post(f"/discussion/{post.id}/delete")

    assert (await db.execute(select(DiscussionPost))).first() is not None


async def test_admin_can_delete_any_post(engine, db, test_admin, test_user, complete_season):
    post = await _add_post(db, complete_season, test_user, 10, "Moderate me")

    async with make_client(engine, test_admin) as client:
        await client.post(f"/discussion/{post.id}/delete")

    assert (await db.execute(select(DiscussionPost))).first() is None
