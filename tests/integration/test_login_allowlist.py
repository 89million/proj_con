"""Integration tests for is_login_allowed() — DB-driven login access control."""

from app.main import is_login_allowed
from app.models import User

# ---------------------------------------------------------------------------
# is_login_allowed — env var takes priority
# ---------------------------------------------------------------------------


async def test_env_var_match_allows_login(db):
    """Email in ALLOWED_EMAILS env var is always allowed regardless of DB state."""
    # settings.allowed_emails is "" in test env (allow-all mode),
    # so is_email_allowed returns True for any email → is_login_allowed returns True.
    assert await is_login_allowed(db, "anyone@example.com") is True


# ---------------------------------------------------------------------------
# is_login_allowed — empty DB bootstrap
# ---------------------------------------------------------------------------


async def test_empty_db_allows_first_login(db, monkeypatch):
    """When the users table is empty, any email is allowed (first-admin bootstrap)."""
    monkeypatch.setattr("app.main.settings.allowed_emails", "first@club.com")
    # DB is empty (no users fixture used)
    assert await is_login_allowed(db, "newcomer@example.com") is True


# ---------------------------------------------------------------------------
# is_login_allowed — DB membership grants access
# ---------------------------------------------------------------------------


async def test_db_registered_email_allowed(db, monkeypatch):
    """A pre-registered email (in users table) is allowed even if not in env var."""
    monkeypatch.setattr("app.main.settings.allowed_emails", "admin@club.com")
    member = User(email="member@club.com", name="Member", google_id=None)
    db.add(member)
    await db.commit()

    assert await is_login_allowed(db, "member@club.com") is True


async def test_db_registered_email_case_insensitive(db, monkeypatch):
    """Email matching in DB check is case-insensitive."""
    monkeypatch.setattr("app.main.settings.allowed_emails", "admin@club.com")
    member = User(email="Member@Club.com", name="Member", google_id=None)
    db.add(member)
    await db.commit()

    assert await is_login_allowed(db, "member@club.com") is True
    assert await is_login_allowed(db, "MEMBER@CLUB.COM") is True


async def test_unknown_email_denied(db, monkeypatch):
    """An email not in DB and not in env var is denied."""
    monkeypatch.setattr("app.main.settings.allowed_emails", "admin@club.com")
    # Add a different user so DB is non-empty (bootstrap doesn't apply)
    db.add(User(email="admin@club.com", name="Admin", google_id="g-admin"))
    await db.commit()

    assert await is_login_allowed(db, "stranger@example.com") is False


async def test_env_var_email_allowed_even_if_not_in_db(db, monkeypatch):
    """Email in ALLOWED_EMAILS env var is allowed even without a DB row."""
    monkeypatch.setattr("app.main.settings.allowed_emails", "bootstrap@club.com")
    # Add some user so DB is non-empty
    db.add(User(email="other@club.com", name="Other", google_id="g-other"))
    await db.commit()

    assert await is_login_allowed(db, "bootstrap@club.com") is True


# ---------------------------------------------------------------------------
# Admin page — allowlist_gaps banner
# ---------------------------------------------------------------------------


async def test_admin_page_shows_gap_warning(engine, test_admin, test_user, monkeypatch):
    """Admin page shows warning when a DB user's email isn't in ALLOWED_EMAILS."""
    from .conftest import make_client

    # test_user email is "user@test.com" — not in the restricted allowlist
    monkeypatch.setattr("app.main.settings.allowed_emails", test_admin.email)

    async with make_client(engine, test_admin) as client:
        resp = await client.get("/admin")

    assert resp.status_code == 200
    assert "ALLOWED_EMAILS" in resp.text
    assert test_user.email in resp.text


async def test_admin_page_no_gap_warning_when_allowlist_empty(engine, test_admin, monkeypatch):
    """No warning shown when ALLOWED_EMAILS is empty (allow-all / dev mode)."""
    from .conftest import make_client

    monkeypatch.setattr("app.main.settings.allowed_emails", "")

    async with make_client(engine, test_admin) as client:
        resp = await client.get("/admin")

    assert resp.status_code == 200
    assert "ALLOWED_EMAILS" not in resp.text


async def test_admin_page_no_gap_warning_when_all_covered(
    engine, test_admin, test_user, monkeypatch
):
    """No warning when all DB users are in ALLOWED_EMAILS."""
    from .conftest import make_client

    both = f"{test_admin.email},{test_user.email}"
    monkeypatch.setattr("app.main.settings.allowed_emails", both)

    async with make_client(engine, test_admin) as client:
        resp = await client.get("/admin")

    assert resp.status_code == 200
    assert "ALLOWED_EMAILS" not in resp.text
