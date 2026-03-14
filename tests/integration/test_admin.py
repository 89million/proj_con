"""Integration tests for admin-only routes."""

import pytest_asyncio
from sqlalchemy import select

from app.models import Book, Season, SeasonState, User

# ---------------------------------------------------------------------------
# Local fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def a_book(db, active_season, test_admin):
    """A single submitted book in the active season."""
    book = Book(
        title="Editable Book",
        author="Some Author",
        page_count=300,
        submitter_id=test_admin.id,
        season_id=active_season.id,
    )
    db.add(book)
    await db.commit()
    await db.refresh(book)
    return book


# ---------------------------------------------------------------------------
# Add / delete users
# ---------------------------------------------------------------------------


async def test_add_user(client_as_admin, db):
    """POST /admin/users/add creates a new pre-registered user."""
    resp = await client_as_admin.post(
        "/admin/users/add", data={"name": "New Member", "email": "new@example.com"}
    )
    assert resp.status_code == 302

    result = await db.execute(select(User).where(User.email == "new@example.com"))
    user = result.scalar_one_or_none()
    assert user is not None
    assert user.name == "New Member"
    assert user.google_id is None  # pre-registered, not yet logged in


async def test_delete_user(client_as_admin, test_user, db):
    """POST /admin/users/{id}/delete removes the user from the DB."""
    resp = await client_as_admin.post(f"/admin/users/{test_user.id}/delete")
    assert resp.status_code == 302

    result = await db.execute(select(User).where(User.id == test_user.id))
    assert result.scalar_one_or_none() is None


async def test_cannot_delete_self(client_as_admin, test_admin, db):
    """Admin cannot delete their own account — the route silently skips the delete."""
    resp = await client_as_admin.post(f"/admin/users/{test_admin.id}/delete")
    assert resp.status_code == 302

    result = await db.execute(select(User).where(User.id == test_admin.id))
    assert result.scalar_one_or_none() is not None


# ---------------------------------------------------------------------------
# Edit / delete books
# ---------------------------------------------------------------------------


async def test_edit_book(client_as_admin, a_book, db):
    """POST /admin/books/{id}/edit updates the book's metadata."""
    resp = await client_as_admin.post(
        f"/admin/books/{a_book.id}/edit",
        data={"title": "Updated Title", "author": "New Author", "page_count": "123"},
    )
    assert resp.status_code == 302

    await db.refresh(a_book)
    assert a_book.title == "Updated Title"
    assert a_book.author == "New Author"
    assert a_book.page_count == 123


async def test_delete_book(client_as_admin, a_book, db):
    """POST /admin/books/{id}/delete removes the book from the DB."""
    resp = await client_as_admin.post(f"/admin/books/{a_book.id}/delete")
    assert resp.status_code == 302

    result = await db.execute(select(Book).where(Book.id == a_book.id))
    assert result.scalar_one_or_none() is None


# ---------------------------------------------------------------------------
# Delete season
# ---------------------------------------------------------------------------


async def test_delete_season(client_as_admin, active_season, db):
    """POST /admin/season/{id}/delete removes the season from the DB."""
    resp = await client_as_admin.post(f"/admin/season/{active_season.id}/delete")
    assert resp.status_code == 302

    result = await db.execute(select(Season).where(Season.id == active_season.id))
    assert result.scalar_one_or_none() is None


# ---------------------------------------------------------------------------
# Force-advance season
# ---------------------------------------------------------------------------


async def test_force_advance_submit_to_ranking(client_as_admin, active_season, db):
    """Force-advancing a season in submit state moves it to ranking."""
    assert active_season.state == SeasonState.submit

    resp = await client_as_admin.post(f"/admin/season/{active_season.id}/advance")
    assert resp.status_code == 302

    await db.refresh(active_season)
    assert active_season.state == SeasonState.ranking


async def test_force_advance_ranking_to_bracket(
    client_as_admin, active_season, a_book, test_user, db
):
    """Force-advancing from ranking creates bracket matchups and moves to bracket state."""
    # Need a second book from a different user (unique constraint: one book per user per season)
    book2 = Book(
        title="Second Book",
        author="Another Author",
        page_count=200,
        submitter_id=test_user.id,
        season_id=active_season.id,
    )
    db.add(book2)
    active_season.state = SeasonState.ranking
    await db.commit()

    resp = await client_as_admin.post(f"/admin/season/{active_season.id}/advance")
    assert resp.status_code == 302

    await db.refresh(active_season)
    assert active_season.state == SeasonState.bracket


async def test_force_advance_bracket_to_complete(client_as_admin, active_season, db):
    """Force-advancing from bracket state marks the season complete."""
    active_season.state = SeasonState.bracket
    await db.commit()

    resp = await client_as_admin.post(f"/admin/season/{active_season.id}/advance")
    assert resp.status_code == 302

    await db.refresh(active_season)
    assert active_season.state == SeasonState.complete
