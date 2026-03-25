"""Integration tests for user settings (display name, email notifications)."""

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
