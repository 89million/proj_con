"""Integration tests for the discussion <-> quote-wall integration.

A discussion post can open from a quote. The quote lands on the book's wall
(so it outlives the season) and the two surfaces cross-link: the wall snapshot
shows on the winner page, and a quote that started a thread links back to it.
"""

import pytest_asyncio
from sqlalchemy import select

from app.models import (
    Book,
    BookQuote,
    BracketMatchup,
    DiscussionPost,
    ReadBook,
    ReadingProgress,
    Season,
    SeasonParticipant,
    SeasonState,
)

from .conftest import make_client


@pytest_asyncio.fixture
async def complete_season(db, test_admin, test_user):
    """Completed season with a 300-page winner and its ReadBook shelf copy."""
    season = Season(name="Link Season", state=SeasonState.complete, page_limit=400)
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
    # The shelf copy a completed season would have created.
    db.add(
        ReadBook(
            title="Winning Book",
            author="Author A",
            won=True,
            added_by=test_admin.id,
            page_count=300,
            season_id=season.id,
        )
    )
    await db.commit()
    await db.refresh(season)
    return season


async def _read_book(db, season):
    return (await db.execute(select(ReadBook).where(ReadBook.season_id == season.id))).scalar_one()


async def _set_progress(db, season, user, percent):
    db.add(ReadingProgress(season_id=season.id, user_id=user.id, percent=percent))
    await db.commit()


# ---------------------------------------------------------------------------
# Posting with a quote
# ---------------------------------------------------------------------------


async def test_posting_with_a_quote_creates_a_wall_quote_and_links_it(
    engine, db, test_user, complete_season
):
    async with make_client(engine, test_user) as client:
        await client.post(
            "/discussion",
            data={"body": "This wrecked me", "anchor_page": "40", "quote_text": "A memorable line"},
        )

    quote = (await db.execute(select(BookQuote))).scalar_one()
    post = (await db.execute(select(DiscussionPost))).scalar_one()

    assert quote.text == "A memorable line"
    assert quote.page == 40, "the quote takes the post's anchor page"
    assert post.quote_id == quote.id


async def test_posting_without_a_quote_creates_no_quote(engine, db, test_user, complete_season):
    async with make_client(engine, test_user) as client:
        await client.post(
            "/discussion", data={"body": "Just a thought", "anchor_page": "40", "quote_text": "  "}
        )

    assert (await db.execute(select(BookQuote))).first() is None
    assert (await db.execute(select(DiscussionPost))).scalar_one().quote_id is None


async def test_quoted_post_shows_the_passage_on_the_winner_page(
    engine, db, test_user, complete_season
):
    async with make_client(engine, test_user) as client:
        await client.post(
            "/discussion",
            data={"body": "Look at this", "anchor_page": "10", "quote_text": "Wickersham parasol"},
        )
        await _set_progress(db, complete_season, test_user, 50)
        html = (await client.get("/complete")).text

    assert "Wickersham parasol" in html


# ---------------------------------------------------------------------------
# The wall snapshot on the winner page
# ---------------------------------------------------------------------------


async def test_winner_page_shows_a_wall_snapshot(engine, db, test_user, complete_season):
    read_book = await _read_book(db, complete_season)
    db.add(
        BookQuote(read_book_id=read_book.id, user_id=test_user.id, page=12, text="Snapshot line")
    )
    await db.commit()

    async with make_client(engine, test_user) as client:
        html = (await client.get("/complete")).text

    assert "From the quote wall" in html
    assert "Snapshot line" in html
    assert f"/history/book/{read_book.id}#quotes" in html


async def test_wall_snapshot_respects_fog(engine, db, test_admin, test_user, complete_season):
    """A snapshot quote from further on is scrambled like anything else."""
    read_book = await _read_book(db, complete_season)
    db.add(
        BookQuote(
            read_book_id=read_book.id, user_id=test_admin.id, page=290, text="Zelophehad ending"
        )
    )
    await db.commit()
    await _set_progress(db, complete_season, test_user, 10)  # p.30

    async with make_client(engine, test_user) as client:
        html = (await client.get("/complete")).text

    assert "Zelophehad" not in html


# ---------------------------------------------------------------------------
# Reverse link: quote -> its discussion thread
# ---------------------------------------------------------------------------


async def test_quote_that_opened_a_thread_links_back_from_the_book_page(
    engine, db, test_user, complete_season
):
    async with make_client(engine, test_user) as client:
        await client.post(
            "/discussion",
            data={"body": "Start here", "anchor_page": "5", "quote_text": "The opening line"},
        )
        read_book = await _read_book(db, complete_season)
        html = (await client.get(f"/history/book/{read_book.id}")).text

    assert "Discussed on the winner page" in html


async def test_plain_wall_quote_has_no_discussion_link(engine, db, test_user, complete_season):
    read_book = await _read_book(db, complete_season)
    db.add(BookQuote(read_book_id=read_book.id, user_id=test_user.id, page=8, text="Just a quote"))
    await db.commit()

    async with make_client(engine, test_user) as client:
        html = (await client.get(f"/history/book/{read_book.id}")).text

    assert "Discussed on the winner page" not in html


async def test_deleting_a_linked_quote_leaves_the_post_standing(
    engine, db, test_user, complete_season
):
    """SET NULL: the post survives, just loses its quote block."""
    async with make_client(engine, test_user) as client:
        await client.post(
            "/discussion",
            data={"body": "Body survives", "anchor_page": "5", "quote_text": "Doomed quote"},
        )
        read_book = await _read_book(db, complete_season)
        quote = (await db.execute(select(BookQuote))).scalar_one()
        await client.post(f"/history/book/{read_book.id}/quote/{quote.id}/delete")

    post = (await db.execute(select(DiscussionPost))).scalar_one()
    assert post.body == "Body survives"
    assert post.quote_id is None
