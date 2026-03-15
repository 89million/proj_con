"""Tests for specific bug fixes.

Each test targets a known bug and should FAIL before the corresponding fix
is applied, then PASS after.
"""

import pytest_asyncio
from sqlalchemy import select

from app.models import Book, BracketMatchup, ReadBook, Season, SeasonParticipant, SeasonState, User

from .conftest import make_client

# ---------------------------------------------------------------------------
# Bug 1 — XSS in /api/suggest-description
# ---------------------------------------------------------------------------


async def test_suggest_description_escapes_html(engine, db, test_user, monkeypatch):
    """AI-generated text containing HTML must be escaped in the response.

    Without escaping, </textarea><script>... breaks out of the textarea
    and executes arbitrary JavaScript.
    """
    dangerous_text = '</textarea><script>alert("xss")</script>'

    # Mock the google genai client to return dangerous text
    class FakeResult:
        text = dangerous_text

    class FakeModels:
        def generate_content(self, **kwargs):
            return FakeResult()

    class FakeClient:
        def __init__(self, **kwargs):
            self.models = FakeModels()

    monkeypatch.setattr("app.main.settings.gemini_api_key", "fake-key")

    import google.genai

    monkeypatch.setattr(google.genai, "Client", FakeClient)

    async with make_client(engine, test_user) as client:
        resp = await client.post(
            "/api/suggest-description",
            data={"title": "Test Book", "author": "Test Author"},
        )

    assert resp.status_code == 200
    # The raw dangerous string must NOT appear unescaped in the response
    assert "<script>" not in resp.text
    # The escaped version should be present
    assert "&lt;script&gt;" in resp.text


# ---------------------------------------------------------------------------
# Bug 2 — Email case mismatch in get_or_create_user
# ---------------------------------------------------------------------------


async def test_oauth_links_preregistered_user_case_insensitive(db):
    """A pre-registered user with mixed-case email should be found and linked
    when they log in via Google with a lowercase version of the same email.

    Bug: auth.py compares emails case-sensitively, so the lookup misses the
    pre-registered row and creates a duplicate user instead of linking.
    """
    from app.auth import get_or_create_user

    # Admin pre-registers a user with mixed-case email
    preregistered = User(
        name="John Doe",
        email="JohnDoe@Gmail.com",
        google_id=None,
        is_admin=False,
    )
    db.add(preregistered)
    await db.commit()
    await db.refresh(preregistered)

    # Google returns lowercase email
    user_info = {
        "sub": "google-id-john",
        "email": "johndoe@gmail.com",
        "name": "John Doe",
        "picture": "https://example.com/avatar.jpg",
    }

    result_user = await get_or_create_user(db, user_info)

    # Should have linked to the pre-registered user, not created a new one
    assert result_user.id == preregistered.id
    assert result_user.google_id == "google-id-john"

    # There should be exactly one user with this email (case-insensitive)
    all_users = (await db.execute(select(User))).scalars().all()
    emails_lower = [u.email.lower() for u in all_users]
    assert emails_lower.count("johndoe@gmail.com") == 1


# ---------------------------------------------------------------------------
# Bug 3 — Deleting a book during bracket state causes FK violation
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def bracket_season_with_matchup(db, test_admin, test_user):
    """Season in bracket state with a real matchup between two books."""
    season = Season(name="Bracket Season", state=SeasonState.submit, page_limit=400)
    db.add(season)
    await db.commit()
    await db.refresh(season)
    db.add(SeasonParticipant(season_id=season.id, user_id=test_admin.id))
    db.add(SeasonParticipant(season_id=season.id, user_id=test_user.id))

    book1 = Book(
        title="Book Alpha",
        author="Author A",
        page_count=200,
        submitter_id=test_admin.id,
        season_id=season.id,
    )
    book2 = Book(
        title="Book Beta",
        author="Author B",
        page_count=250,
        submitter_id=test_user.id,
        season_id=season.id,
    )
    db.add_all([book1, book2])
    await db.flush()

    matchup = BracketMatchup(
        season_id=season.id,
        round=1,
        position=1,
        book_a_id=book1.id,
        book_b_id=book2.id,
    )
    db.add(matchup)
    season.state = SeasonState.bracket
    await db.commit()
    await db.refresh(book1)
    await db.refresh(book2)
    await db.refresh(matchup)
    return season, book1, book2, matchup


async def test_delete_book_during_bracket_succeeds(
    client_as_admin, bracket_season_with_matchup, db
):
    """Deleting a book that appears in bracket matchups must not crash.

    Bug: _delete_book_data doesn't clean up BracketMatchup rows that
    reference the book (book_a_id, book_b_id, winner_id), causing an
    IntegrityError on the foreign key constraint.
    """
    season, book1, book2, matchup = bracket_season_with_matchup

    resp = await client_as_admin.post(f"/admin/books/{book1.id}/delete")
    # Should succeed with a redirect, not a 500
    assert resp.status_code == 302

    result = await db.execute(select(Book).where(Book.id == book1.id))
    assert result.scalar_one_or_none() is None


async def test_delete_user_during_bracket_succeeds(
    client_as_admin, bracket_season_with_matchup, db
):
    """Deleting a user whose book is in a bracket matchup must not crash.

    Bug: delete_user → _delete_book_data doesn't handle bracket matchup FKs.
    """
    season, book1, book2, matchup = bracket_season_with_matchup

    # book2 belongs to test_user; delete that user
    resp = await client_as_admin.post(f"/admin/users/{book2.submitter_id}/delete")
    assert resp.status_code == 302

    result = await db.execute(select(User).where(User.id == book2.submitter_id))
    assert result.scalar_one_or_none() is None


# ---------------------------------------------------------------------------
# Bug 4 — Force-advance ranking→bracket with < 2 books creates dead-end
# ---------------------------------------------------------------------------


async def test_force_advance_ranking_with_one_book_does_not_enter_bracket(
    client_as_admin, db, test_admin
):
    """Force-advancing from ranking with only 1 book should NOT move to bracket.

    Bug: the season transitions to bracket state with no matchups, creating a
    dead-end where get_winner_book_for_season returns None and the season is
    stuck showing "Results are being tallied..." forever.
    """
    season = Season(name="Tiny Season", state=SeasonState.ranking, page_limit=400)
    db.add(season)
    await db.commit()
    await db.refresh(season)

    # Only one book
    db.add(
        Book(
            title="Lonely Book",
            author="Solo Author",
            page_count=200,
            submitter_id=test_admin.id,
            season_id=season.id,
        )
    )
    await db.commit()

    resp = await client_as_admin.post(f"/admin/season/{season.id}/advance")
    assert resp.status_code == 302

    await db.refresh(season)
    # Season should NOT be in bracket state with 0 matchups
    assert season.state != SeasonState.bracket


async def test_force_advance_ranking_with_zero_books_does_not_enter_bracket(
    client_as_admin, db, test_admin
):
    """Force-advancing from ranking with 0 books should NOT move to bracket."""
    season = Season(name="Empty Season", state=SeasonState.ranking, page_limit=400)
    db.add(season)
    await db.commit()
    await db.refresh(season)

    resp = await client_as_admin.post(f"/admin/season/{season.id}/advance")
    assert resp.status_code == 302

    await db.refresh(season)
    assert season.state != SeasonState.bracket


# ---------------------------------------------------------------------------
# Bug 5 — Editing a winner book doesn't update the read_books table
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def completed_season_with_winner(db, test_admin, test_user):
    """A completed season whose winner has a corresponding ReadBook entry."""
    season = Season(name="Done Season", state=SeasonState.submit, page_limit=400)
    db.add(season)
    await db.commit()
    await db.refresh(season)

    book1 = Book(
        title="Old Winner Title",
        author="Old Author",
        page_count=300,
        submitter_id=test_admin.id,
        season_id=season.id,
    )
    book2 = Book(
        title="Loser Book",
        author="Loser Author",
        page_count=250,
        submitter_id=test_user.id,
        season_id=season.id,
    )
    db.add_all([book1, book2])
    await db.flush()

    matchup = BracketMatchup(
        season_id=season.id,
        round=1,
        position=1,
        book_a_id=book1.id,
        book_b_id=book2.id,
        winner_id=book1.id,
    )
    db.add(matchup)

    # The ReadBook snapshot created when the season completed
    rb = ReadBook(
        title="Old Winner Title",
        author="Old Author",
        won=True,
        added_by=test_admin.id,
    )
    db.add(rb)
    season.state = SeasonState.complete
    await db.commit()
    await db.refresh(book1)
    await db.refresh(rb)
    return season, book1, rb


async def test_editing_winner_book_updates_read_books(
    client_as_admin, completed_season_with_winner, db
):
    """When the admin edits a book that won a completed season, the
    corresponding ReadBook entry should also be updated.

    Bug: update_book only touches the books table; the read_books snapshot
    keeps stale title/author, breaking fuzzy-match duplicate blocking and
    showing wrong info in the 'Previously Read Books' admin list.
    """
    season, winner_book, read_book = completed_season_with_winner

    resp = await client_as_admin.post(
        f"/admin/books/{winner_book.id}/edit",
        data={
            "title": "Corrected Title",
            "author": "Corrected Author",
            "page_count": "300",
        },
    )
    assert resp.status_code == 302

    await db.refresh(winner_book)
    assert winner_book.title == "Corrected Title"

    await db.refresh(read_book)
    assert read_book.title == "Corrected Title"
    assert read_book.author == "Corrected Author"
