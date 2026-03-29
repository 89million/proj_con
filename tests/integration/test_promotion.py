"""Integration tests for the promotion / relegation feature."""

import pytest_asyncio
from sqlalchemy import select

from app import crud
from app.models import Book, BordaVote, BracketMatchup, Season, SeasonParticipant, SeasonState, Seed

from .conftest import make_client

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _complete_season_with_seeds(db, season, books, winner_book, users):
    """Set up a fully completed season: seeds + final matchup with a winner.

    `books` should be ordered best-seed-first.  `winner_book` must be in `books`.
    Every user in `users` submits a Borda ranking matching the book order.
    """
    season.state = SeasonState.ranking
    await db.flush()

    # Borda votes from each user matching the given order
    for user in users:
        for rank, book in enumerate(books, start=1):
            db.add(BordaVote(user_id=user.id, season_id=season.id, book_id=book.id, rank=rank))

    # Seeds matching the order
    for seed_num, book in enumerate(books, start=1):
        db.add(Seed(season_id=season.id, book_id=book.id, seed=seed_num))

    # Final matchup — just need a winner recorded
    runner_up = [b for b in books if b.id != winner_book.id][0]
    matchup = BracketMatchup(
        season_id=season.id,
        round=99,
        position=1,
        book_a_id=winner_book.id,
        book_b_id=runner_up.id,
        winner_id=winner_book.id,
    )
    db.add(matchup)
    season.state = SeasonState.complete
    await db.commit()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def completed_season(db, test_admin, test_user):
    """A completed season with 4 books seeded 1-4, book1 as winner.

    Returns (season, book1, book2, book3, book4) where book1 won.
    book1 & book2 submitted by test_admin, book3 & book4 by test_user.
    """
    season = Season(name="Prior Season", state=SeasonState.submit, page_limit=400)
    db.add(season)
    await db.commit()
    await db.refresh(season)

    db.add(SeasonParticipant(season_id=season.id, user_id=test_admin.id))
    db.add(SeasonParticipant(season_id=season.id, user_id=test_user.id))

    books = []
    for i, (title, author, submitter) in enumerate(
        [
            ("Winner Book", "Auth A", test_admin),
            ("Silver Book", "Auth B", test_admin),
            ("Bronze Book", "Auth C", test_user),
            ("Fourth Book", "Auth D", test_user),
        ]
    ):
        b = Book(
            title=title,
            author=author,
            page_count=200,
            submitter_id=submitter.id,
            season_id=season.id,
        )
        db.add(b)
        books.append(b)
    await db.flush()

    await _complete_season_with_seeds(
        db, season, books, winner_book=books[0], users=[test_admin, test_user]
    )
    for b in books:
        await db.refresh(b)
    await db.refresh(season)
    return (season, *books)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_promote_books_on_season_creation(
    client_as_admin, completed_season, db, test_admin, test_user
):
    """Creating a new season auto-promotes top N non-winners from the prior completed season."""
    prior_season, winner, silver, bronze, fourth = completed_season

    resp = await client_as_admin.post(
        "/admin/season", data={"name": "New Season", "page_limit": 400}
    )
    assert resp.status_code == 302

    # Find the new season
    result = await db.execute(select(Season).where(Season.name == "New Season"))
    new_season = result.scalar_one()

    # Promoted books: silver (seed 2) and bronze (seed 3) — winner excluded
    promoted = await db.execute(
        select(Book).where(Book.season_id == new_season.id, Book.promoted == True)  # noqa: E712
    )
    promoted_books = list(promoted.scalars().all())
    promoted_titles = {b.title for b in promoted_books}

    assert len(promoted_books) == 2
    assert "Silver Book" in promoted_titles
    assert "Bronze Book" in promoted_titles
    assert "Winner Book" not in promoted_titles


async def test_no_promotion_first_season(client_as_admin, db):
    """When there's no prior completed season, creating a season doesn't crash."""
    resp = await client_as_admin.post(
        "/admin/season", data={"name": "First Ever", "page_limit": 400}
    )
    assert resp.status_code == 302

    result = await db.execute(select(Season).where(Season.name == "First Ever"))
    new_season = result.scalar_one()

    promoted = await db.execute(
        select(Book).where(Book.season_id == new_season.id, Book.promoted == True)  # noqa: E712
    )
    assert list(promoted.scalars().all()) == []


async def test_promoted_user_can_still_submit(
    client_as_admin, completed_season, db, engine, test_user
):
    """A user whose book was promoted can still submit a different new book."""
    prior_season, winner, silver, bronze, fourth = completed_season

    # Create new season (promotes silver + bronze)
    await client_as_admin.post("/admin/season", data={"name": "New Season", "page_limit": 400})
    result = await db.execute(select(Season).where(Season.name == "New Season"))
    new_season = result.scalar_one()

    # test_user had bronze promoted — they should still be able to submit a new book
    async with make_client(engine, test_user) as user_client:
        resp = await user_client.post(
            "/submit",
            data={"title": "Fresh Pick", "author": "New Author", "page_count": 300},
        )
    assert resp.status_code == 302

    # Verify both the promoted book and the new submission exist
    all_books = await db.execute(
        select(Book).where(Book.season_id == new_season.id, Book.submitter_id == test_user.id)
    )
    user_books = list(all_books.scalars().all())
    assert len(user_books) == 2
    titles = {b.title for b in user_books}
    assert "Bronze Book" in titles  # promoted
    assert "Fresh Pick" in titles  # new submission


async def test_promoted_book_blocks_duplicate_submission(
    client_as_admin, completed_season, db, engine, test_user
):
    """Submitting a book with the same title+author as a promoted book is blocked."""
    prior_season, winner, silver, bronze, fourth = completed_season

    await client_as_admin.post("/admin/season", data={"name": "New Season", "page_limit": 400})

    # Try to submit same title/author as the promoted "Bronze Book"
    async with make_client(engine, test_user) as user_client:
        resp = await user_client.post(
            "/submit",
            data={"title": "Bronze Book", "author": "Auth C", "page_count": 200},
        )
    # Should get an error (either 200 with error message or the unique constraint blocks it)
    assert resp.status_code == 200 or resp.status_code == 500
    if resp.status_code == 200:
        assert "already" in resp.text.lower() or "duplicate" in resp.text.lower()


async def test_relegation_excludes_bottom_books(
    client_as_admin, completed_season, db, engine, test_admin, test_user, extra_user
):
    """After ranking, bottom N books are excluded from the bracket matchups."""
    prior_season, winner, silver, bronze, fourth = completed_season

    # Create new season with promoted books
    await client_as_admin.post("/admin/season", data={"name": "New Season", "page_limit": 400})
    result = await db.execute(select(Season).where(Season.name == "New Season"))
    new_season = result.scalar_one()

    # extra_user is already a participant (POST /admin/season enrolls all users)

    # Add manual submissions from all three users
    manual_books = []
    for title, author, submitter in [
        ("Admin Pick", "Auth X", test_admin),
        ("User Pick", "Auth Y", test_user),
        ("Extra Pick", "Auth Z", extra_user),
    ]:
        b = Book(
            title=title,
            author=author,
            page_count=200,
            submitter_id=submitter.id,
            season_id=new_season.id,
        )
        db.add(b)
        manual_books.append(b)
    await db.flush()

    # Advance to ranking
    new_season.state = SeasonState.ranking
    await db.commit()

    # Get all books for this season (promoted + manual)
    all_books = await crud.get_books_for_season(db, new_season.id)
    assert len(all_books) == 5  # 2 promoted + 3 manual

    # All 3 users rank all 5 books — same order for simplicity
    book_ids_by_order = [b.id for b in sorted(all_books, key=lambda b: b.title)]
    for user in [test_admin, test_user, extra_user]:
        for rank, book_id in enumerate(book_ids_by_order, start=1):
            db.add(BordaVote(user_id=user.id, season_id=new_season.id, book_id=book_id, rank=rank))
    await db.commit()

    # Trigger advance by having the last user submit their ranking via HTTP
    # But since we already added votes directly, let's use the state machine
    from app.state import maybe_advance_from_ranking

    advanced = await maybe_advance_from_ranking(db, new_season)
    assert advanced is True

    # Check bracket matchups — bottom 2 books should be excluded
    matchups = await db.execute(
        select(BracketMatchup).where(BracketMatchup.season_id == new_season.id)
    )
    matchup_list = list(matchups.scalars().all())
    bracket_book_ids = set()
    for m in matchup_list:
        bracket_book_ids.add(m.book_a_id)
        bracket_book_ids.add(m.book_b_id)

    # 5 books - 2 relegated = 3 in bracket
    assert len(bracket_book_ids) == 3

    # The seeds are saved for ALL 5 books
    seeds = await db.execute(select(Seed).where(Seed.season_id == new_season.id))
    seed_list = list(seeds.scalars().all())
    assert len(seed_list) == 5


async def test_relegation_safety_net(db, test_admin, test_user):
    """With too few books, relegation doesn't fire — all books enter the bracket."""
    # Create completed season with only 2 books
    season1 = Season(name="Tiny Season", state=SeasonState.submit, page_limit=400)
    db.add(season1)
    await db.commit()
    await db.refresh(season1)
    db.add(SeasonParticipant(season_id=season1.id, user_id=test_admin.id))
    db.add(SeasonParticipant(season_id=season1.id, user_id=test_user.id))

    b1 = Book(
        title="Only A",
        author="Auth",
        page_count=100,
        submitter_id=test_admin.id,
        season_id=season1.id,
    )
    b2 = Book(
        title="Only B",
        author="Auth",
        page_count=100,
        submitter_id=test_user.id,
        season_id=season1.id,
    )
    db.add_all([b1, b2])
    await db.flush()

    await _complete_season_with_seeds(
        db, season1, [b1, b2], winner_book=b1, users=[test_admin, test_user]
    )

    # New season with 1 promoted book + 2 manual = 3 total
    season2 = Season(name="Small Season", state=SeasonState.submit, page_limit=400)
    db.add(season2)
    await db.commit()
    await db.refresh(season2)
    db.add(SeasonParticipant(season_id=season2.id, user_id=test_admin.id))
    db.add(SeasonParticipant(season_id=season2.id, user_id=test_user.id))

    promoted = await crud.promote_books_to_season(db, season1.id, season2.id, 2)
    # Only 1 promotable (b2, since b1 won)
    assert len(promoted) == 1

    m1 = Book(
        title="New A",
        author="Auth",
        page_count=100,
        submitter_id=test_admin.id,
        season_id=season2.id,
    )
    m2 = Book(
        title="New B",
        author="Auth",
        page_count=100,
        submitter_id=test_user.id,
        season_id=season2.id,
    )
    db.add_all([m1, m2])
    await db.flush()

    season2.state = SeasonState.ranking
    all_books = await crud.get_books_for_season(db, season2.id)
    # 3 books total — relegating 2 would leave 1 < min_bracket_size=2 → safety net
    for user in [test_admin, test_user]:
        for rank, book in enumerate(all_books, start=1):
            db.add(BordaVote(user_id=user.id, season_id=season2.id, book_id=book.id, rank=rank))
    await db.commit()

    from app.state import maybe_advance_from_ranking

    advanced = await maybe_advance_from_ranking(db, season2)
    assert advanced is True

    # All 3 books should be in the bracket (safety net prevented relegation)
    matchups = await db.execute(
        select(BracketMatchup).where(BracketMatchup.season_id == season2.id)
    )
    bracket_book_ids = set()
    for m in matchups.scalars().all():
        bracket_book_ids.add(m.book_a_id)
        bracket_book_ids.add(m.book_b_id)
    assert len(bracket_book_ids) == 3


async def test_count_submissions_excludes_promoted(db, test_admin, test_user):
    """count_submissions only counts manual books, not promoted ones."""
    season = Season(name="Count Test", state=SeasonState.submit, page_limit=400)
    db.add(season)
    await db.commit()
    await db.refresh(season)

    # Add a promoted book
    db.add(
        Book(
            title="Promo",
            author="Auth",
            page_count=100,
            submitter_id=test_admin.id,
            season_id=season.id,
            promoted=True,
        )
    )
    # Add a manual book
    db.add(
        Book(
            title="Manual",
            author="Auth",
            page_count=100,
            submitter_id=test_user.id,
            season_id=season.id,
        )
    )
    await db.commit()

    count = await crud.count_submissions(db, season.id)
    assert count == 1  # only the manual book


async def test_waiting_on_includes_promoted_user(db, test_admin, test_user):
    """A user whose book was promoted still appears on the 'waiting on' list."""
    season = Season(name="Waiting Test", state=SeasonState.submit, page_limit=400)
    db.add(season)
    await db.commit()
    await db.refresh(season)

    db.add(SeasonParticipant(season_id=season.id, user_id=test_admin.id))
    db.add(SeasonParticipant(season_id=season.id, user_id=test_user.id))

    # test_user has a promoted book but no manual submission
    db.add(
        Book(
            title="Promo Book",
            author="Auth",
            page_count=100,
            submitter_id=test_user.id,
            season_id=season.id,
            promoted=True,
        )
    )
    await db.commit()

    waiting = await crud.users_who_havent_submitted(db, season.id)
    waiting_ids = {u.id for u in waiting}

    # Both users should be waiting — promoted book doesn't count as a submission
    assert test_admin.id in waiting_ids
    assert test_user.id in waiting_ids
