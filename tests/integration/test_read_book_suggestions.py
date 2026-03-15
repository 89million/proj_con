"""Tests for the 'Books We've Read' user suggestion + admin approval workflow."""

from sqlalchemy import select

from app.models import ReadBook

from .conftest import make_client


async def test_user_can_submit_read_book(engine, db, test_user):
    """A logged-in user can suggest a book via POST /history/suggest-book."""
    async with make_client(engine, test_user) as client:
        resp = await client.post(
            "/history/suggest-book",
            data={"title": "Dune", "author": "Frank Herbert"},
        )

    assert resp.status_code == 302

    result = await db.execute(select(ReadBook).where(ReadBook.title == "Dune"))
    rb = result.scalar_one()
    assert rb.author == "Frank Herbert"
    assert rb.pending is True
    assert rb.won is False
    assert rb.added_by == test_user.id


async def test_submitted_book_not_visible_until_approved(engine, db, test_user):
    """Pending books should NOT appear on the books tab."""
    # Submit a book (creates pending entry)
    async with make_client(engine, test_user) as client:
        await client.post(
            "/history/suggest-book",
            data={"title": "Neuromancer", "author": "William Gibson"},
        )

        resp = await client.get("/history", params={"tab": "books"})

    assert resp.status_code == 200
    assert "Neuromancer" not in resp.text


async def test_admin_approves_pending_book(engine, db, test_admin, test_user):
    """After admin approval, the book appears on the books tab."""
    # User submits
    async with make_client(engine, test_user) as client:
        await client.post(
            "/history/suggest-book",
            data={"title": "Kindred", "author": "Octavia Butler"},
        )

    result = await db.execute(select(ReadBook).where(ReadBook.title == "Kindred"))
    rb = result.scalar_one()
    assert rb.pending is True

    # Admin approves
    async with make_client(engine, test_admin) as client:
        resp = await client.post(f"/admin/read-books/{rb.id}/approve")

    assert resp.status_code == 302

    await db.refresh(rb)
    assert rb.pending is False

    # Now visible on books tab
    async with make_client(engine, test_user) as client:
        resp = await client.get("/history", params={"tab": "books"})
    assert "Kindred" in resp.text


async def test_admin_rejects_pending_book(engine, db, test_admin, test_user):
    """Rejecting a pending book deletes it."""
    async with make_client(engine, test_user) as client:
        await client.post(
            "/history/suggest-book",
            data={"title": "Bad Suggestion", "author": "Nobody"},
        )

    result = await db.execute(select(ReadBook).where(ReadBook.title == "Bad Suggestion"))
    rb = result.scalar_one()

    async with make_client(engine, test_admin) as client:
        resp = await client.post(f"/admin/read-books/{rb.id}/reject")

    assert resp.status_code == 302

    result = await db.execute(select(ReadBook).where(ReadBook.title == "Bad Suggestion"))
    assert result.scalar_one_or_none() is None


async def test_books_tab_lists_approved_books(engine, db, test_admin, test_user):
    """GET /history?tab=books shows approved books alphabetically."""
    from app import crud

    await crud.add_read_book(
        db, "Zen and the Art", "Robert Pirsig", won=False, added_by=test_admin.id
    )
    await crud.add_read_book(db, "Animal Farm", "George Orwell", won=True, added_by=test_admin.id)

    async with make_client(engine, test_user) as client:
        resp = await client.get("/history", params={"tab": "books"})

    assert resp.status_code == 200
    # Both should appear
    assert "Animal Farm" in resp.text
    assert "Zen and the Art" in resp.text
    # Animal Farm should appear before Zen (alphabetical)
    assert resp.text.index("Animal Farm") < resp.text.index("Zen and the Art")


async def test_history_default_tab_is_seasons(engine, db, test_user):
    """GET /history without tab param defaults to showing the seasons tab."""
    async with make_client(engine, test_user) as client:
        resp = await client.get("/history")

    assert resp.status_code == 200
    assert "Seasons" in resp.text
