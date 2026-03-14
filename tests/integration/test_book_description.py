"""Integration tests for the optional book description field."""

from sqlalchemy import select

from app.models import Book, Season, SeasonParticipant, SeasonState

from .conftest import make_client


async def test_submit_without_description_ok(engine, db, test_admin, test_user):
    """Submitting a book without a description saves successfully."""
    season = Season(name="No Desc Season", state=SeasonState.submit, page_limit=400)
    db.add(season)
    await db.commit()
    await db.refresh(season)
    db.add(SeasonParticipant(season_id=season.id, user_id=test_user.id))
    await db.commit()

    async with make_client(engine, test_user) as client:
        resp = await client.post(
            "/submit",
            data={"title": "Dune", "author": "Frank Herbert", "page_count": "300"},
        )

    assert resp.status_code in (200, 302)
    book = (await db.execute(select(Book).where(Book.season_id == season.id))).scalar_one_or_none()
    assert book is not None
    assert book.description is None


async def test_submit_with_description_saves_and_displays(engine, db, test_admin, test_user):
    """Submitting a book with a description stores it and shows it on the submit page."""
    season = Season(name="Desc Season", state=SeasonState.submit, page_limit=400)
    db.add(season)
    await db.commit()
    await db.refresh(season)
    # Enroll both users so the season doesn't auto-advance after test_user submits
    db.add(SeasonParticipant(season_id=season.id, user_id=test_user.id))
    db.add(SeasonParticipant(season_id=season.id, user_id=test_admin.id))
    await db.commit()

    async with make_client(engine, test_user) as client:
        await client.post(
            "/submit",
            data={
                "title": "Dune",
                "author": "Frank Herbert",
                "page_count": "300",
                "description": "A sci-fi epic set in a desert world.",
            },
        )
        # Now GET the submit page — should show the description
        resp = await client.get("/submit")

    assert resp.status_code == 200
    assert "A sci-fi epic set in a desert world." in resp.text


async def test_description_shown_in_submissions_list(engine, db, test_admin, test_user):
    """Other users can see a description in the submissions list."""
    season = Season(name="List Desc Season", state=SeasonState.submit, page_limit=400)
    db.add(season)
    await db.commit()
    await db.refresh(season)
    db.add(SeasonParticipant(season_id=season.id, user_id=test_admin.id))
    db.add(SeasonParticipant(season_id=season.id, user_id=test_user.id))
    # Admin submits a book with a description directly in the DB
    db.add(
        Book(
            title="Foundation",
            author="Isaac Asimov",
            page_count=244,
            description="A sweeping tale of the fall of a galactic empire.",
            submitter_id=test_admin.id,
            season_id=season.id,
        )
    )
    await db.commit()

    # Regular user views submit page — should see description in submissions list
    async with make_client(engine, test_user) as client:
        resp = await client.get("/submit")

    assert resp.status_code == 200
    assert "A sweeping tale of the fall of a galactic empire." in resp.text


async def test_admin_edit_sets_description(engine, db, test_admin):
    """Admin can set a description via the inline edit form."""
    season = Season(name="Edit Desc Season", state=SeasonState.submit, page_limit=400)
    db.add(season)
    await db.commit()
    await db.refresh(season)
    book = Book(
        title="Neuromancer",
        author="William Gibson",
        page_count=271,
        submitter_id=test_admin.id,
        season_id=season.id,
    )
    db.add(book)
    await db.commit()
    await db.refresh(book)

    async with make_client(engine, test_admin) as client:
        resp = await client.post(
            f"/admin/books/{book.id}/edit",
            data={
                "title": "Neuromancer",
                "author": "William Gibson",
                "page_count": "271",
                "description": "A cyberpunk noir novel following a washed-up hacker.",
            },
        )

    assert resp.status_code in (200, 302)
    await db.refresh(book)
    assert book.description == "A cyberpunk noir novel following a washed-up hacker."


async def test_admin_edit_clears_description(engine, db, test_admin):
    """Admin can clear a description by submitting an empty value."""
    season = Season(name="Clear Desc Season", state=SeasonState.submit, page_limit=400)
    db.add(season)
    await db.commit()
    await db.refresh(season)
    book = Book(
        title="Snow Crash",
        author="Neal Stephenson",
        page_count=440,
        description="Existing description.",
        submitter_id=test_admin.id,
        season_id=season.id,
    )
    db.add(book)
    await db.commit()
    await db.refresh(book)

    async with make_client(engine, test_admin) as client:
        await client.post(
            f"/admin/books/{book.id}/edit",
            data={
                "title": "Snow Crash",
                "author": "Neal Stephenson",
                "page_count": "440",
                "description": "",
            },
        )

    await db.refresh(book)
    assert book.description is None
