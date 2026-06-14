"""Tests for the admin cover-backfill (core function + admin route)."""

from unittest.mock import AsyncMock, patch

import app.main as main
from app import crud
from app.models import Season, SeasonState


async def _season(db):
    season = Season(name="S", state=SeasonState.submit, page_limit=400)
    db.add(season)
    await db.commit()
    await db.refresh(season)
    return season


async def test_backfill_fills_only_missing_covers(db, test_user):
    season = await _season(db)
    await crud.create_book(
        db, "Has Cover", "A", 100, test_user.id, season.id, cover_url="https://covers/x.jpg"
    )
    await crud.create_book(db, "Needs Cover", "B", 100, test_user.id, season.id)

    with patch.object(
        main, "fetch_cover_url", new=AsyncMock(return_value="https://covers/new.jpg")
    ):
        updated, total = await main.backfill_book_covers(db)

    assert (updated, total) == (1, 1)  # only the cover-less book was looked up
    books = {b.title: b for b in await crud.get_books_for_season(db, season.id)}
    assert books["Has Cover"].cover_url == "https://covers/x.jpg"  # untouched
    assert books["Needs Cover"].cover_url == "https://covers/new.jpg"


async def test_backfill_leaves_book_when_no_cover_found(db, test_user):
    season = await _season(db)
    await crud.create_book(db, "Obscure", "Nobody", 100, test_user.id, season.id)

    with patch.object(main, "fetch_cover_url", new=AsyncMock(return_value=None)):
        updated, total = await main.backfill_book_covers(db)

    assert (updated, total) == (0, 1)
    books = await crud.get_books_for_season(db, season.id)
    assert books[0].cover_url is None  # stays on placeholder, no crash


async def test_admin_backfill_route_requires_admin_and_updates(client_as_admin, db, test_user):
    season = await _season(db)
    await crud.create_book(db, "Needs Cover", "B", 100, test_user.id, season.id)

    with patch.object(main, "fetch_cover_url", new=AsyncMock(return_value="https://covers/c.jpg")):
        resp = await client_as_admin.post("/admin/backfill-covers")

    assert resp.status_code == 302
    assert resp.headers["location"] == "/admin?toast=covers_filled"
    books = await crud.get_books_for_season(db, season.id)
    assert books[0].cover_url == "https://covers/c.jpg"


async def test_backfill_also_fills_read_books(db, test_admin):
    """The backfill covers the 'books we've read' list too, not just season books."""
    await crud.add_read_book(db, "Old Read", "Author", won=True, added_by=test_admin.id)

    with patch.object(main, "fetch_cover_url", new=AsyncMock(return_value="https://covers/r.jpg")):
        updated, total = await main.backfill_book_covers(db)

    assert (updated, total) == (1, 1)
    read_books = await crud.get_approved_read_books(db)
    assert read_books[0].cover_url == "https://covers/r.jpg"


async def test_admin_add_read_book_sets_cover(client_as_admin, db):
    """Adding a read book via the admin form looks up and stores its cover."""
    with patch.object(main, "fetch_cover_url", new=AsyncMock(return_value="https://covers/k.jpg")):
        resp = await client_as_admin.post(
            "/admin/read-books", data={"title": "Klara and the Sun", "author": "Ishiguro"}
        )
    assert resp.status_code == 302
    read_books = await crud.get_approved_read_books(db)
    assert read_books[0].cover_url == "https://covers/k.jpg"
