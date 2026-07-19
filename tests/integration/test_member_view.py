"""Integration tests for the admin "member view" toggle."""

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.auth import create_session_token
from app.database import get_db
from app.main import app, get_user_or_none, require_admin, require_user

from .conftest import make_client

BANNER_TEXT = "You're seeing the site as a regular member"
SWITCH_BACK = "Switch back to admin view"
NAV_TOGGLE = "Member view"


def make_cookie_client(engine):
    """Client that overrides only the DB, so real cookie-based auth runs."""
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    for dep in (get_user_or_none, require_user, require_admin):
        app.dependency_overrides.pop(dep, None)

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ---------------------------------------------------------------------------
# Toggle route
# ---------------------------------------------------------------------------


async def test_toggle_sets_cookie_and_returns_to_page(engine, test_admin):
    """POST /toggle-member-view sets the cookie and bounces back to the page."""
    async with make_client(engine, test_admin) as client:
        resp = await client.post("/toggle-member-view", data={"return_to": "/complete"})
    assert resp.status_code == 302
    assert resp.headers["location"] == "/complete"
    assert "member_view=1" in resp.headers.get("set-cookie", "")


async def test_toggle_clears_cookie_when_set(engine, test_admin):
    """Toggling again clears the member_view cookie."""
    async with make_client(engine, test_admin) as client:
        client.cookies.set("member_view", "1")
        resp = await client.post("/toggle-member-view", data={"return_to": "/complete"})
    assert resp.status_code == 302
    set_cookie = resp.headers.get("set-cookie", "")
    assert "member_view" in set_cookie
    assert "member_view=1" not in set_cookie  # deletion, not re-set


async def test_toggle_rejects_external_return_to(engine, test_admin):
    """Absolute or protocol-relative return_to values fall back to /."""
    for bad in ("https://evil.example/", "//evil.example/x"):
        async with make_client(engine, test_admin) as client:
            resp = await client.post("/toggle-member-view", data={"return_to": bad})
        assert resp.status_code == 302
        assert resp.headers["location"] == "/"


async def test_toggle_is_noop_for_non_admin(engine, test_user):
    """Non-admins get redirected but never receive the cookie."""
    async with make_client(engine, test_user) as client:
        resp = await client.post("/toggle-member-view", data={"return_to": "/complete"})
    assert resp.status_code == 302
    assert "member_view" not in resp.headers.get("set-cookie", "")


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


async def test_admin_sees_admin_ui_and_toggle_by_default(engine, test_admin):
    """Without the cookie an admin sees admin UI plus the nav toggle, no banner."""
    async with make_client(engine, test_admin) as client:
        resp = await client.get("/complete")
    assert resp.status_code == 200
    assert "Start Next Season" in resp.text
    assert NAV_TOGGLE in resp.text
    assert BANNER_TEXT not in resp.text


async def test_member_view_hides_admin_ui_and_shows_banner(engine, test_admin):
    """With member_view active, admin widgets vanish and the banner appears."""
    test_admin.member_view = True
    async with make_client(engine, test_admin) as client:
        resp = await client.get("/complete")
    assert resp.status_code == 200
    assert "Start Next Season" not in resp.text
    assert 'href="/admin"' not in resp.text
    assert BANNER_TEXT in resp.text
    assert SWITCH_BACK in resp.text


async def test_regular_member_never_sees_banner_or_toggle(engine, test_user):
    """Non-admins see neither the toggle nor the member-view banner."""
    async with make_client(engine, test_user) as client:
        resp = await client.get("/complete")
    assert resp.status_code == 200
    assert NAV_TOGGLE not in resp.text
    assert BANNER_TEXT not in resp.text


# ---------------------------------------------------------------------------
# End-to-end via real cookie auth (no dependency overrides)
# ---------------------------------------------------------------------------


async def test_cookie_flows_through_real_auth(engine, test_admin):
    """The member_view cookie shapes the UI when auth runs for real."""
    async with make_cookie_client(engine) as client:
        client.cookies.set("session", create_session_token(test_admin.id))
        client.cookies.set("member_view", "1")
        resp = await client.get("/complete")
    assert resp.status_code == 200
    assert "Start Next Season" not in resp.text
    assert BANNER_TEXT in resp.text


async def test_cookie_never_blocks_admin_routes(engine, test_admin):
    """Member view is cosmetic: admin authorization is untouched by the cookie."""
    async with make_cookie_client(engine) as client:
        client.cookies.set("session", create_session_token(test_admin.id))
        client.cookies.set("member_view", "1")
        resp = await client.get("/admin")
    assert resp.status_code == 200
