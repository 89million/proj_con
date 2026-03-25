"""Integration tests for book star ratings and reviews."""

import pytest_asyncio

from app.models import BookReview, ReadBook

from .conftest import make_client


@pytest_asyncio.fixture
async def read_book(db, test_user):
    """An approved read book."""
    rb = ReadBook(title="Dune", author="Frank Herbert", won=True, added_by=test_user.id)
    db.add(rb)
    await db.commit()
    await db.refresh(rb)
    return rb


@pytest_asyncio.fixture
async def pending_book(db, test_user):
    """A pending read book (not yet approved)."""
    rb = ReadBook(
        title="Pending Book", author="Unknown", won=False, pending=True, added_by=test_user.id
    )
    db.add(rb)
    await db.commit()
    await db.refresh(rb)
    return rb


# ---------------------------------------------------------------------------
# Book detail page
# ---------------------------------------------------------------------------


async def test_book_detail_page_accessible(engine, test_user, read_book):
    """GET /history/book/{id} returns 200 for an approved book."""
    async with make_client(engine, test_user) as client:
        resp = await client.get(f"/history/book/{read_book.id}")
    assert resp.status_code == 200
    assert "Dune" in resp.text
    assert "Frank Herbert" in resp.text


async def test_book_detail_404_for_pending(engine, test_user, pending_book):
    """GET /history/book/{id} returns 404 for a pending book."""
    async with make_client(engine, test_user) as client:
        resp = await client.get(f"/history/book/{pending_book.id}")
    assert resp.status_code == 404


async def test_book_detail_404_for_nonexistent(engine, test_user):
    """GET /history/book/999 returns 404."""
    async with make_client(engine, test_user) as client:
        resp = await client.get("/history/book/999")
    assert resp.status_code == 404


async def test_book_detail_shows_no_ratings_message(engine, test_user, read_book):
    """A book with no reviews shows 'No ratings yet'."""
    async with make_client(engine, test_user) as client:
        resp = await client.get(f"/history/book/{read_book.id}")
    assert "No ratings yet" in resp.text


# ---------------------------------------------------------------------------
# Submitting reviews
# ---------------------------------------------------------------------------


async def test_submit_rating_only(engine, db, test_user, read_book):
    """Submitting a rating without review text works."""
    async with make_client(engine, test_user) as client:
        resp = await client.post(
            f"/history/book/{read_book.id}/review",
            data={"rating": "4", "review_text": ""},
        )
    assert resp.status_code == 302

    async with make_client(engine, test_user) as client:
        resp = await client.get(f"/history/book/{read_book.id}")
    assert resp.status_code == 200
    assert "4" in resp.text


async def test_submit_rating_with_review(engine, db, test_user, read_book):
    """Submitting a rating with review text persists both."""
    async with make_client(engine, test_user) as client:
        resp = await client.post(
            f"/history/book/{read_book.id}/review",
            data={"rating": "5", "review_text": "An absolute masterpiece."},
        )
    assert resp.status_code == 302

    async with make_client(engine, test_user) as client:
        resp = await client.get(f"/history/book/{read_book.id}")
    assert "An absolute masterpiece." in resp.text
    assert "5" in resp.text


async def test_update_existing_review(engine, db, test_user, read_book):
    """Posting again updates rather than creating a second review."""
    async with make_client(engine, test_user) as client:
        await client.post(
            f"/history/book/{read_book.id}/review",
            data={"rating": "3", "review_text": "It was okay."},
        )
    async with make_client(engine, test_user) as client:
        await client.post(
            f"/history/book/{read_book.id}/review",
            data={"rating": "5", "review_text": "Changed my mind, loved it."},
        )

    async with make_client(engine, test_user) as client:
        resp = await client.get(f"/history/book/{read_book.id}")
    assert "Changed my mind, loved it." in resp.text
    assert "It was okay." not in resp.text


async def test_invalid_rating_rejected(engine, test_user, read_book):
    """Rating outside 1-5 returns 422."""
    async with make_client(engine, test_user) as client:
        resp = await client.post(
            f"/history/book/{read_book.id}/review",
            data={"rating": "0", "review_text": ""},
        )
    assert resp.status_code == 422

    async with make_client(engine, test_user) as client:
        resp = await client.post(
            f"/history/book/{read_book.id}/review",
            data={"rating": "6", "review_text": ""},
        )
    assert resp.status_code == 422


async def test_review_pending_book_404(engine, test_user, pending_book):
    """Cannot review a pending book."""
    async with make_client(engine, test_user) as client:
        resp = await client.post(
            f"/history/book/{pending_book.id}/review",
            data={"rating": "4", "review_text": ""},
        )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Multiple reviewers
# ---------------------------------------------------------------------------


async def test_multiple_users_review(engine, db, test_user, extra_user, read_book):
    """Multiple users can each leave their own review."""
    async with make_client(engine, test_user) as client:
        await client.post(
            f"/history/book/{read_book.id}/review",
            data={"rating": "4", "review_text": "Great book!"},
        )
    async with make_client(engine, extra_user) as client:
        await client.post(
            f"/history/book/{read_book.id}/review",
            data={"rating": "2", "review_text": "Not my cup of tea."},
        )

    async with make_client(engine, test_user) as client:
        resp = await client.get(f"/history/book/{read_book.id}")
    assert "Great book!" in resp.text
    assert "Not my cup of tea." in resp.text
    assert "3.0 avg" in resp.text


# ---------------------------------------------------------------------------
# History page shows ratings
# ---------------------------------------------------------------------------


async def test_history_books_tab_shows_avg_rating(engine, db, test_user, read_book):
    """The books tab shows average star ratings."""
    review = BookReview(read_book_id=read_book.id, user_id=test_user.id, rating=4, review_text=None)
    db.add(review)
    await db.commit()

    async with make_client(engine, test_user) as client:
        resp = await client.get("/history?tab=books")
    assert resp.status_code == 200
    assert "4.0" in resp.text


async def test_history_books_tab_links_to_detail(engine, test_user, read_book):
    """Each book card links to the detail page."""
    async with make_client(engine, test_user) as client:
        resp = await client.get("/history?tab=books")
    assert f"/history/book/{read_book.id}" in resp.text
