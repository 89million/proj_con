"""Integration tests for the book submission flow."""

from app.models import Book, ReadBook

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_submit_happy_path(client_as_user, active_season):
    """Valid submission → 302, book appears on the submit page."""
    resp = await client_as_user.post(
        "/submit", data={"title": "My Book", "author": "Great Author", "page_count": 200}
    )
    assert resp.status_code == 302

    page = await client_as_user.get("/submit")
    assert page.status_code == 200
    assert "My Book" in page.text


async def test_submit_duplicate_blocked(client_as_user, active_season):
    """Second submission by the same user is rejected with an error message."""
    data = {"title": "First Book", "author": "Author One", "page_count": 150}
    await client_as_user.post("/submit", data=data)

    resp = await client_as_user.post("/submit", data=data)
    assert resp.status_code == 200
    assert "already submitted" in resp.text


async def test_submit_over_page_limit(client_as_user, active_season):
    """Submission exceeding the season page limit is rejected."""
    # active_season.page_limit == 400
    resp = await client_as_user.post(
        "/submit", data={"title": "Huge Book", "author": "Verbose Author", "page_count": 401}
    )
    assert resp.status_code == 200
    assert "400" in resp.text  # page limit appears in the error


async def test_submit_won_book_blocked(client_as_user, active_season, test_admin, db):
    """A book that won a previous season cannot be submitted again."""
    won = ReadBook(title="Old Champion", author="Famous Author", won=True, added_by=test_admin.id)
    db.add(won)
    await db.commit()

    resp = await client_as_user.post(
        "/submit",
        data={"title": "Old Champion", "author": "Famous Author", "page_count": 300},
    )
    assert resp.status_code == 200
    assert "won" in resp.text.lower()


async def test_submit_previously_read_non_winner_blocked(
    client_as_user, active_season, test_admin, db
):
    """A book that was read (but didn't win) is also blocked from re-submission."""
    read = ReadBook(title="Been There", author="Done That", won=False, added_by=test_admin.id)
    db.add(read)
    await db.commit()

    resp = await client_as_user.post(
        "/submit",
        data={"title": "Been There", "author": "Done That", "page_count": 250},
    )
    assert resp.status_code == 200
    assert "read" in resp.text.lower()


async def test_submit_season_advances_to_ranking(client_as_admin, active_season, db, test_user):
    """When all participants submit, the season auto-advances to ranking."""
    # test_user pre-submits via DB (they're already a participant)
    db.add(
        Book(
            title="User's Pick",
            author="Another Author",
            page_count=200,
            submitter_id=test_user.id,
            season_id=active_season.id,
        )
    )
    await db.commit()

    # test_admin (last participant) submits — triggers advance
    resp = await client_as_admin.post(
        "/submit", data={"title": "Admin's Pick", "author": "An Author", "page_count": 300}
    )
    assert resp.status_code == 302

    # /submit now redirects away (season is no longer in submit state)
    page = await client_as_admin.get("/submit")
    assert page.status_code == 302

    # /ranking is now accessible
    ranking_page = await client_as_admin.get("/ranking")
    assert ranking_page.status_code == 200
