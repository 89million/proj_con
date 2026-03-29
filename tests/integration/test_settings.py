"""Integration tests for user settings (display name, email notifications)."""

from unittest.mock import patch

from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport

from app.main import app, get_db, get_user_or_none, require_user

from .conftest import make_client


async def test_settings_page_accessible(engine, test_user):
    """GET /settings returns 200 for logged-in users."""
    async with make_client(engine, test_user) as client:
        resp = await client.get("/settings")
    assert resp.status_code == 200
    assert "Settings" in resp.text


async def test_save_display_name(engine, db, test_user):
    """Setting a display name persists and shows up in the nav."""
    async with make_client(engine, test_user) as client:
        resp = await client.post(
            "/settings",
            data={"display_name": "Cool Nickname", "email_notifications": "on"},
        )
    assert resp.status_code == 302

    await db.refresh(test_user)
    assert test_user.display_name == "Cool Nickname"
    assert test_user.visible_name == "Cool Nickname"


async def test_clear_display_name_falls_back_to_google_name(engine, db, test_user):
    """Clearing the display name reverts to the Google account name."""
    test_user.display_name = "Old Nick"
    await db.commit()

    async with make_client(engine, test_user) as client:
        resp = await client.post(
            "/settings",
            data={"display_name": "", "email_notifications": "on"},
        )
    assert resp.status_code == 302

    await db.refresh(test_user)
    assert test_user.display_name is None
    assert test_user.visible_name == test_user.name


async def test_disable_email_notifications(engine, db, test_user):
    """Unchecking email notifications sets the flag to False."""
    assert test_user.email_notifications is True

    async with make_client(engine, test_user) as client:
        resp = await client.post(
            "/settings",
            data={"display_name": "", "email_notifications": "off"},
        )
    assert resp.status_code == 302

    await db.refresh(test_user)
    assert test_user.email_notifications is False


async def test_enable_email_notifications(engine, db, test_user):
    """Checking email notifications sets the flag to True."""
    test_user.email_notifications = False
    await db.commit()

    async with make_client(engine, test_user) as client:
        resp = await client.post(
            "/settings",
            data={"display_name": "", "email_notifications": "on"},
        )
    assert resp.status_code == 302

    await db.refresh(test_user)
    assert test_user.email_notifications is True


async def test_saved_banner_shown(engine, test_user):
    """After saving, the page shows a 'Settings saved!' banner."""
    async with make_client(engine, test_user) as client:
        resp = await client.get("/settings?saved=1")
    assert resp.status_code == 200
    assert "Settings saved!" in resp.text


async def test_display_name_shown_in_nav(engine, db, test_user):
    """The display name appears in the navigation bar."""
    test_user.display_name = "BookWorm42"
    await db.commit()

    async with make_client(engine, test_user) as client:
        resp = await client.get("/settings")
    assert resp.status_code == 200
    assert "BookWorm42" in resp.text


async def test_delete_account_deactivates_user(engine, db, test_user):
    """POST /settings/delete-account sets is_active=False and email_notifications=False."""
    assert test_user.is_active is True

    async with make_client(engine, test_user) as client:
        resp = await client.post("/settings/delete-account")

    assert resp.status_code == 302
    assert "account_deleted=1" in resp.headers["location"]

    await db.refresh(test_user)
    assert test_user.is_active is False
    assert test_user.email_notifications is False


async def test_delete_account_clears_session_cookie(engine, db, test_user):
    """POST /settings/delete-account clears the session cookie."""
    async with make_client(engine, test_user) as client:
        resp = await client.post("/settings/delete-account")

    assert resp.status_code == 302
    # Cookie should be cleared (set with empty value or max-age=0)
    set_cookie = resp.headers.get("set-cookie", "")
    assert "session" in set_cookie


async def test_deactivated_user_blocked_from_login(engine, db, test_user):
    """A deactivated user is redirected to /?error=deactivated when logging in via OAuth."""
    test_user.is_active = False
    await db.commit()

    from sqlalchemy.ext.asyncio import async_sessionmaker

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    # Remove user override so auth_callback uses the real DB path
    app.dependency_overrides.pop(get_user_or_none, None)
    app.dependency_overrides.pop(require_user, None)

    fake_user_info = {
        "email": test_user.email,
        "name": test_user.name,
        "sub": test_user.google_id or "google-sub-123",
        "picture": None,
    }
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            with patch("app.main.exchange_code_for_user_info", return_value=fake_user_info):
                resp = await client.get("/auth/callback?code=fake")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 302
    assert "error=deactivated" in resp.headers["location"]
