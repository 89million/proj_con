"""Integration tests for admin-only routes."""

import pytest_asyncio
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.database import get_db
from app.main import app, get_user_or_none, require_admin, require_user
from app.models import Book, Season, SeasonState, User


def make_client_with_real_auth(engine, current_user):
    """Like make_client but enforces the admin check for require_admin."""
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_db():
        async with session_factory() as session:
            yield session

    async def override_user():
        return current_user

    async def override_require_admin():
        if current_user is None:
            raise HTTPException(status_code=302, headers={"Location": "/auth/login"})
        if not current_user.is_admin:
            raise HTTPException(status_code=403, detail="Admin access required.")
        return current_user

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_user_or_none] = override_user
    app.dependency_overrides[require_user] = override_user
    app.dependency_overrides[require_admin] = override_require_admin

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


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


# ---------------------------------------------------------------------------
# Admin access control — non-admin users are blocked
# ---------------------------------------------------------------------------


async def test_non_admin_cannot_access_admin_page(engine, test_user):
    """A regular user receives 403 when requesting GET /admin."""
    async with make_client_with_real_auth(engine, test_user) as client:
        resp = await client.get("/admin")
    assert resp.status_code == 403
    app.dependency_overrides.clear()


async def test_non_admin_cannot_create_season(engine, test_user):
    """A regular user receives 403 when posting to POST /admin/season."""
    async with make_client_with_real_auth(engine, test_user) as client:
        resp = await client.post(
            "/admin/season", data={"name": "Sneaky Season", "page_limit": "400"}
        )
    assert resp.status_code == 403
    app.dependency_overrides.clear()


async def test_admin_can_access_admin_page(engine, test_admin):
    """An admin user receives 200 on GET /admin."""
    async with make_client_with_real_auth(engine, test_admin) as client:
        resp = await client.get("/admin")
    assert resp.status_code == 200
    app.dependency_overrides.clear()


async def test_toggle_admin_role(client_as_admin, test_user, db):
    """Admin can toggle another user's admin status."""
    assert test_user.is_admin is False

    resp = await client_as_admin.post(f"/admin/users/{test_user.id}/toggle-admin")
    assert resp.status_code == 302

    await db.refresh(test_user)
    assert test_user.is_admin is True

    # Toggle back
    resp = await client_as_admin.post(f"/admin/users/{test_user.id}/toggle-admin")
    assert resp.status_code == 302
    await db.refresh(test_user)
    assert test_user.is_admin is False
