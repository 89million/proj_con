"""Integration tests for the book quote wall and review spoiler gating.

Both hang off the book page. Quotes are page-anchored and scrambled the same
way discussion posts are; review text is withheld until the reader finishes,
because a review is a verdict on the whole book rather than on one page.
"""

import pytest_asyncio
from sqlalchemy import select

from app.models import BookQuote, BookReview, ReadBook, ReadingProgress, Season, SeasonState

from .conftest import make_client

ENDING = "Elizabeth is murdered on the wedding night and Victor understands everything"
OPENING = "Walton's framing device is the best decision in the whole novel"


@pytest_asyncio.fixture
async def read_book(db, test_admin):
    """A 300-page book tied to a completed season, as a real winner would be."""
    season = Season(name="Quote Season", state=SeasonState.complete, page_limit=400)
    db.add(season)
    await db.flush()

    rb = ReadBook(
        title="The Winner",
        author="Some Author",
        won=True,
        added_by=test_admin.id,
        page_count=300,
        season_id=season.id,
    )
    db.add(rb)
    await db.commit()
    await db.refresh(rb)
    return rb


@pytest_asyncio.fixture
async def orphan_book(db, test_admin):
    """A book backfilled from before the app existed: no season, no page count."""
    rb = ReadBook(title="Old Read", author="Ancient", won=False, added_by=test_admin.id)
    db.add(rb)
    await db.commit()
    await db.refresh(rb)
    return rb


async def _set_progress(db, book, user, percent):
    db.add(ReadingProgress(season_id=book.season_id, user_id=user.id, percent=percent))
    await db.commit()


async def _add_quote(db, book, user, page, text):
    quote = BookQuote(read_book_id=book.id, user_id=user.id, page=page, text=text)
    db.add(quote)
    await db.commit()
    await db.refresh(quote)
    return quote


# ---------------------------------------------------------------------------
# Quotes
# ---------------------------------------------------------------------------


async def test_adding_a_quote_stores_text_and_page(engine, db, test_user, read_book):
    async with make_client(engine, test_user) as client:
        resp = await client.post(
            f"/history/book/{read_book.id}/quote", data={"text": "A fine line", "page": "42"}
        )

    assert resp.status_code == 302
    quote = (await db.execute(select(BookQuote))).scalar_one()
    assert quote.text == "A fine line"
    assert quote.page == 42
    assert quote.read_book_id == read_book.id


async def test_page_is_clamped_to_the_books_length(engine, db, test_user, read_book):
    async with make_client(engine, test_user) as client:
        await client.post(
            f"/history/book/{read_book.id}/quote", data={"text": "Past the end", "page": "9999"}
        )

    assert (await db.execute(select(BookQuote))).scalar_one().page == 300


async def test_blank_quote_is_rejected(engine, db, test_user, read_book):
    async with make_client(engine, test_user) as client:
        await client.post(f"/history/book/{read_book.id}/quote", data={"text": "  ", "page": "10"})

    assert (await db.execute(select(BookQuote))).first() is None


async def test_quote_from_further_on_is_scrambled(engine, db, test_user, test_admin, read_book):
    await _add_quote(db, read_book, test_admin, 280, ENDING)
    await _set_progress(db, read_book, test_user, 10)  # p.30 of 300

    async with make_client(engine, test_user) as client:
        html = (await client.get(f"/history/book/{read_book.id}")).text

    for word in ("Elizabeth", "murdered", "wedding", "Victor"):
        assert word not in html, f"{word!r} leaked from a quote"


async def test_quote_you_have_reached_is_readable(engine, db, test_user, test_admin, read_book):
    await _add_quote(db, read_book, test_admin, 20, OPENING)
    await _set_progress(db, read_book, test_user, 50)  # p.150

    async with make_client(engine, test_user) as client:
        html = (await client.get(f"/history/book/{read_book.id}")).text

    assert "framing device" in html


async def test_your_own_quote_is_never_scrambled_to_you(engine, db, test_user, read_book):
    await _add_quote(db, read_book, test_user, 290, ENDING)
    await _set_progress(db, read_book, test_user, 0)

    async with make_client(engine, test_user) as client:
        html = (await client.get(f"/history/book/{read_book.id}")).text

    assert "Elizabeth" in html


async def test_books_without_a_page_count_are_never_gated(
    engine, db, test_user, test_admin, orphan_book
):
    """A pre-app book has no length and no season, so nothing can be inferred."""
    await _add_quote(db, orphan_book, test_admin, 100, ENDING)

    async with make_client(engine, test_user) as client:
        html = (await client.get(f"/history/book/{orphan_book.id}")).text

    assert "Elizabeth" in html


async def test_reader_who_never_checked_in_sees_everything(
    engine, db, test_user, test_admin, read_book
):
    """No progress row means we can't guess — assume they've read it."""
    await _add_quote(db, read_book, test_admin, 290, ENDING)

    async with make_client(engine, test_user) as client:
        html = (await client.get(f"/history/book/{read_book.id}")).text

    assert "Elizabeth" in html


async def test_author_can_delete_their_quote(engine, db, test_user, read_book):
    quote = await _add_quote(db, read_book, test_user, 10, "Never mind")

    async with make_client(engine, test_user) as client:
        await client.post(f"/history/book/{read_book.id}/quote/{quote.id}/delete")

    assert (await db.execute(select(BookQuote))).first() is None


async def test_member_cannot_delete_someone_elses_quote(
    engine, db, test_user, test_admin, read_book
):
    quote = await _add_quote(db, read_book, test_admin, 10, "Mine")

    async with make_client(engine, test_user) as client:
        await client.post(f"/history/book/{read_book.id}/quote/{quote.id}/delete")

    assert (await db.execute(select(BookQuote))).first() is not None


# ---------------------------------------------------------------------------
# Review gating — the spoiler hole
# ---------------------------------------------------------------------------


async def _add_review(db, book, user, rating, text):
    db.add(BookReview(read_book_id=book.id, user_id=user.id, rating=rating, review_text=text))
    await db.commit()


async def test_review_text_is_hidden_from_a_reader_mid_book(
    engine, db, test_user, test_admin, read_book
):
    """The original hole: anyone could read a finished member's review."""
    await _add_review(db, read_book, test_admin, 5, ENDING)
    await _set_progress(db, read_book, test_user, 80)

    async with make_client(engine, test_user) as client:
        html = (await client.get(f"/history/book/{read_book.id}")).text

    assert "Elizabeth" not in html
    assert "Hidden until you finish" in html


async def test_rating_still_shows_while_the_text_is_hidden(
    engine, db, test_user, test_admin, read_book
):
    """A star rating spoils nothing, so averages keep working."""
    await _add_review(db, read_book, test_admin, 4, ENDING)
    await _set_progress(db, read_book, test_user, 80)

    async with make_client(engine, test_user) as client:
        html = (await client.get(f"/history/book/{read_book.id}")).text

    assert "4.0 avg" in html
    assert "Elizabeth" not in html


async def test_finishing_reveals_every_review(engine, db, test_user, test_admin, read_book):
    await _add_review(db, read_book, test_admin, 5, ENDING)
    await _set_progress(db, read_book, test_user, 100)

    async with make_client(engine, test_user) as client:
        html = (await client.get(f"/history/book/{read_book.id}")).text

    assert "Elizabeth" in html


async def test_your_own_review_is_always_visible_to_you(engine, db, test_user, read_book):
    await _add_review(db, read_book, test_user, 3, ENDING)
    await _set_progress(db, read_book, test_user, 20)

    async with make_client(engine, test_user) as client:
        html = (await client.get(f"/history/book/{read_book.id}")).text

    assert "Elizabeth" in html


async def test_past_season_books_are_not_gated(engine, db, test_user, test_admin, orphan_book):
    await _add_review(db, orphan_book, test_admin, 5, ENDING)

    async with make_client(engine, test_user) as client:
        html = (await client.get(f"/history/book/{orphan_book.id}")).text

    assert "Elizabeth" in html
