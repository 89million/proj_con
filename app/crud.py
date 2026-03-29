"""All database read/write operations."""

from datetime import datetime

from rapidfuzz.distance import Levenshtein
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    Book,
    BookReview,
    BordaVote,
    BracketMatchup,
    BracketVote,
    FeatureIdea,
    IdeaStatus,
    IdeaUpvote,
    Meetup,
    MeetupOption,
    MeetupVote,
    ReadBook,
    Season,
    SeasonParticipant,
    SeasonState,
    Seed,
    User,
)

# ---------------------------------------------------------------------------
# Season
# ---------------------------------------------------------------------------


async def get_active_season(db: AsyncSession) -> Season | None:
    """Return the most recent non-complete season, or the most recently
    created season overall if everything is complete.  This keeps the
    just-finished season visible until a new one is started."""
    result = await db.execute(
        select(Season)
        .where(Season.state != SeasonState.complete)
        .order_by(Season.created_at.desc())
        .limit(1)
    )
    season = result.scalar_one_or_none()
    if season is not None:
        return season

    # All seasons are complete — return the most recently created one
    result = await db.execute(select(Season).order_by(Season.created_at.desc()).limit(1))
    return result.scalar_one_or_none()


async def get_season_by_id(db: AsyncSession, season_id: int) -> Season | None:
    result = await db.execute(select(Season).where(Season.id == season_id))
    return result.scalar_one_or_none()


async def create_season(db: AsyncSession, name: str, page_limit: int) -> Season:
    season = Season(name=name, page_limit=page_limit)
    db.add(season)
    await db.commit()
    await db.refresh(season)
    return season


async def set_season_state(db: AsyncSession, season: Season, state: SeasonState) -> None:
    season.state = state
    await db.commit()


async def get_most_recent_complete_season(db: AsyncSession) -> Season | None:
    result = await db.execute(
        select(Season)
        .where(Season.state == SeasonState.complete)
        .order_by(Season.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_complete_seasons(db: AsyncSession) -> list[Season]:
    result = await db.execute(
        select(Season)
        .where(Season.state == SeasonState.complete)
        .order_by(Season.created_at.desc())
    )
    return list(result.scalars().all())


async def get_winner_book_for_season(db: AsyncSession, season_id: int) -> "Book | None":
    matchups = await get_matchups_for_season(db, season_id)
    if not matchups:
        return None
    max_round = max(m.round for m in matchups)
    final = next((m for m in matchups if m.round == max_round and m.winner_id), None)
    if not final:
        return None
    books = await get_books_for_season(db, season_id)
    return next((b for b in books if b.id == final.winner_id), None)


async def get_promotable_books(db: AsyncSession, season_id: int, count: int) -> list[Book]:
    """Top `count` non-winning books from a completed season, ordered by seed (best first)."""
    winner = await get_winner_book_for_season(db, season_id)
    winner_id = winner.id if winner else None

    query = (
        select(Book)
        .join(Seed, and_(Seed.book_id == Book.id, Seed.season_id == season_id))
        .where(Book.season_id == season_id)
    )
    if winner_id is not None:
        query = query.where(Book.id != winner_id)
    result = await db.execute(query.order_by(Seed.seed.asc()).limit(count))
    return list(result.scalars().all())


async def promote_books_to_season(
    db: AsyncSession, source_season_id: int, target_season_id: int, count: int
) -> list[Book]:
    """Auto-promote top non-winning books from source into target season."""
    promotable = await get_promotable_books(db, source_season_id, count)
    promoted = []
    for book in promotable:
        new_book = Book(
            title=book.title,
            author=book.author,
            page_count=book.page_count,
            description=book.description,
            submitter_id=book.submitter_id,
            season_id=target_season_id,
            promoted=True,
        )
        db.add(new_book)
        promoted.append(new_book)
    await db.commit()
    for b in promoted:
        await db.refresh(b)
    return promoted


async def get_all_seasons(db: AsyncSession) -> list[Season]:
    result = await db.execute(select(Season).order_by(Season.created_at.desc()))
    return list(result.scalars().all())


async def get_all_seasons_with_books(db: AsyncSession) -> list[Season]:
    result = await db.execute(
        select(Season).options(selectinload(Season.books)).order_by(Season.created_at.desc())
    )
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Season participants
# ---------------------------------------------------------------------------


async def add_participant(db: AsyncSession, season_id: int, user_id: int) -> SeasonParticipant:
    """Enroll a user in a season. Safe to call if already enrolled (no-op)."""
    existing = await db.execute(
        select(SeasonParticipant).where(
            and_(SeasonParticipant.season_id == season_id, SeasonParticipant.user_id == user_id)
        )
    )
    sp = existing.scalar_one_or_none()
    if sp is not None:
        return sp
    sp = SeasonParticipant(season_id=season_id, user_id=user_id)
    db.add(sp)
    await db.commit()
    await db.refresh(sp)
    return sp


async def remove_participant(db: AsyncSession, season_id: int, user_id: int) -> bool:
    existing = await db.execute(
        select(SeasonParticipant).where(
            and_(SeasonParticipant.season_id == season_id, SeasonParticipant.user_id == user_id)
        )
    )
    sp = existing.scalar_one_or_none()
    if sp is None:
        return False
    await db.delete(sp)
    await db.commit()
    return True


async def get_participants_for_season(db: AsyncSession, season_id: int) -> list[User]:
    result = await db.execute(
        select(User)
        .join(SeasonParticipant, SeasonParticipant.user_id == User.id)
        .where(SeasonParticipant.season_id == season_id)
        .order_by(User.name)
    )
    return list(result.scalars().all())


async def count_participants(db: AsyncSession, season_id: int) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(SeasonParticipant)
        .where(SeasonParticipant.season_id == season_id)
    )
    return result.scalar_one()


async def is_participant(db: AsyncSession, season_id: int, user_id: int) -> bool:
    result = await db.execute(
        select(SeasonParticipant).where(
            and_(SeasonParticipant.season_id == season_id, SeasonParticipant.user_id == user_id)
        )
    )
    return result.scalar_one_or_none() is not None


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


async def get_all_users(db: AsyncSession) -> list[User]:
    result = await db.execute(select(User).order_by(User.name))
    return list(result.scalars().all())


async def get_user_by_id(db: AsyncSession, user_id: int) -> User | None:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Books / submissions
# ---------------------------------------------------------------------------


async def get_books_for_season(db: AsyncSession, season_id: int) -> list[Book]:
    result = await db.execute(
        select(Book)
        .where(Book.season_id == season_id)
        .options(selectinload(Book.submitter))
        .order_by(Book.submitted_at)
    )
    return list(result.scalars().all())


async def get_book_submitted_by_user(db: AsyncSession, user_id: int, season_id: int) -> Book | None:
    """Return the user's manual (non-promoted) submission for this season, if any."""
    result = await db.execute(
        select(Book).where(
            and_(
                Book.submitter_id == user_id,
                Book.season_id == season_id,
                Book.promoted == False,  # noqa: E712
            )
        )
    )
    return result.scalar_one_or_none()


async def create_book(
    db: AsyncSession,
    title: str,
    author: str,
    page_count: int,
    submitter_id: int,
    season_id: int,
    description: str | None = None,
) -> Book:
    book = Book(
        title=title,
        author=author,
        page_count=page_count,
        description=description,
        submitter_id=submitter_id,
        season_id=season_id,
    )
    db.add(book)
    await db.commit()
    await db.refresh(book)
    return book


async def count_submissions(db: AsyncSession, season_id: int) -> int:
    """Count manual (non-promoted) submissions for auto-advance logic."""
    result = await db.execute(
        select(func.count())
        .select_from(Book)
        .where(Book.season_id == season_id, Book.promoted == False)  # noqa: E712
    )
    return result.scalar_one()


async def count_users(db: AsyncSession) -> int:
    result = await db.execute(select(func.count()).select_from(User))
    return result.scalar_one()


# ---------------------------------------------------------------------------
# Read books (admin-managed)
# ---------------------------------------------------------------------------


async def get_all_read_books(db: AsyncSession) -> list[ReadBook]:
    result = await db.execute(select(ReadBook).order_by(ReadBook.title))
    return list(result.scalars().all())


# Maximum edit distances for fuzzy duplicate detection.
# Both title AND author must be within their thresholds to trigger a block,
# so a different author still protects a book with a similar title.
_TITLE_FUZZ_MAX = 2  # e.g. "Bloodchild" vs "Bloodchils" (1 edit) → blocked
_AUTHOR_FUZZ_MAX = 3  # e.g. "Octavia Butler" vs "Octavia E. Butler" (3 edits) → blocked


def _title_matches(a: str, b: str) -> bool:
    return Levenshtein.distance(a.lower(), b.lower()) <= _TITLE_FUZZ_MAX


def _author_matches(a: str, b: str) -> bool:
    return Levenshtein.distance(a.lower(), b.lower()) <= _AUTHOR_FUZZ_MAX


async def is_book_blocked(
    db: AsyncSession, title: str, author: str, season_id: int
) -> tuple[bool, str]:
    """
    Returns (is_blocked, reason).
    Blocked if title+author fuzzy-match (within edit-distance thresholds):
    - any entry in the read books list (won or otherwise), OR
    - any book already submitted this season
    """
    read_books = await get_all_read_books(db)
    for rb in read_books:
        if _title_matches(title, rb.title) and _author_matches(author, rb.author):
            if rb.won:
                return True, "This book won a previous season and cannot be re-submitted."
            return True, "This book has already been read by the club and cannot be re-submitted."

    season_books = await get_books_for_season(db, season_id)
    for book in season_books:
        if _title_matches(title, book.title) and _author_matches(author, book.author):
            return True, "This book has already been submitted this season."

    return False, ""


async def is_read_book_duplicate(db: AsyncSession, title: str, author: str) -> bool:
    """Check if title+author fuzzy-matches any existing read book (pending or approved)."""
    read_books = await get_all_read_books(db)
    for rb in read_books:
        if _title_matches(title, rb.title) and _author_matches(author, rb.author):
            return True
    return False


async def add_read_book(
    db: AsyncSession, title: str, author: str, won: bool, added_by: int
) -> ReadBook:
    rb = ReadBook(title=title, author=author, won=won, added_by=added_by)
    db.add(rb)
    await db.commit()
    await db.refresh(rb)
    return rb


async def delete_read_book(db: AsyncSession, read_book_id: int) -> bool:
    result = await db.execute(select(ReadBook).where(ReadBook.id == read_book_id))
    rb = result.scalar_one_or_none()
    if rb is None:
        return False
    await db.delete(rb)
    await db.commit()
    return True


async def get_approved_read_books(db: AsyncSession) -> list[ReadBook]:
    result = await db.execute(
        select(ReadBook).where(ReadBook.pending.is_(False)).order_by(ReadBook.title)
    )
    return list(result.scalars().all())


async def get_pending_read_books(db: AsyncSession) -> list[ReadBook]:
    result = await db.execute(
        select(ReadBook)
        .where(ReadBook.pending.is_(True))
        .options(selectinload(ReadBook.added_by_user))
        .order_by(ReadBook.added_at)
    )
    return list(result.scalars().all())


async def submit_read_book(db: AsyncSession, title: str, author: str, added_by: int) -> ReadBook:
    rb = ReadBook(title=title, author=author, won=False, pending=True, added_by=added_by)
    db.add(rb)
    await db.commit()
    await db.refresh(rb)
    return rb


async def approve_read_book(db: AsyncSession, read_book_id: int) -> bool:
    result = await db.execute(select(ReadBook).where(ReadBook.id == read_book_id))
    rb = result.scalar_one_or_none()
    if rb is None:
        return False
    rb.pending = False
    await db.commit()
    return True


# ---------------------------------------------------------------------------
# Book reviews / ratings
# ---------------------------------------------------------------------------


async def get_review_for_user(
    db: AsyncSession, read_book_id: int, user_id: int
) -> BookReview | None:
    result = await db.execute(
        select(BookReview).where(
            BookReview.read_book_id == read_book_id, BookReview.user_id == user_id
        )
    )
    return result.scalar_one_or_none()


async def get_reviews_for_book(db: AsyncSession, read_book_id: int) -> list[BookReview]:
    result = await db.execute(
        select(BookReview)
        .where(BookReview.read_book_id == read_book_id)
        .options(selectinload(BookReview.user))
        .order_by(BookReview.created_at.desc())
    )
    return list(result.scalars().all())


async def save_review(
    db: AsyncSession, read_book_id: int, user_id: int, rating: int, review_text: str | None
) -> BookReview:
    """Create or update a user's review for a read book."""
    existing = await get_review_for_user(db, read_book_id, user_id)
    if existing:
        existing.rating = rating
        existing.review_text = review_text
    else:
        existing = BookReview(
            read_book_id=read_book_id, user_id=user_id, rating=rating, review_text=review_text
        )
        db.add(existing)
    await db.commit()
    await db.refresh(existing)
    return existing


async def get_average_ratings(db: AsyncSession) -> dict[int, float]:
    """Return {read_book_id: avg_rating} for all books that have at least one review."""
    result = await db.execute(
        select(BookReview.read_book_id, func.avg(BookReview.rating)).group_by(
            BookReview.read_book_id
        )
    )
    return {row[0]: round(float(row[1]), 1) for row in result.all()}


async def get_review_counts(db: AsyncSession) -> dict[int, int]:
    """Return {read_book_id: count} for all books that have at least one review."""
    result = await db.execute(
        select(BookReview.read_book_id, func.count()).group_by(BookReview.read_book_id)
    )
    return {row[0]: row[1] for row in result.all()}


# ---------------------------------------------------------------------------
# Borda votes
# ---------------------------------------------------------------------------


async def save_borda_votes(
    db: AsyncSession, user_id: int, season_id: int, ranked_book_ids: list[int]
) -> None:
    """ranked_book_ids[0] is the user's top pick (rank=1)."""
    for rank, book_id in enumerate(ranked_book_ids, start=1):
        vote = BordaVote(user_id=user_id, season_id=season_id, book_id=book_id, rank=rank)
        db.add(vote)
    await db.commit()


async def get_borda_votes_for_user(
    db: AsyncSession, user_id: int, season_id: int
) -> list[BordaVote]:
    result = await db.execute(
        select(BordaVote)
        .where(and_(BordaVote.user_id == user_id, BordaVote.season_id == season_id))
        .order_by(BordaVote.rank)
    )
    return list(result.scalars().all())


async def get_all_borda_votes_for_season(db: AsyncSession, season_id: int) -> list[BordaVote]:
    result = await db.execute(select(BordaVote).where(BordaVote.season_id == season_id))
    return list(result.scalars().all())


async def count_borda_voters(db: AsyncSession, season_id: int) -> int:
    """Number of distinct users who have submitted rankings."""
    result = await db.execute(
        select(func.count(BordaVote.user_id.distinct())).where(BordaVote.season_id == season_id)
    )
    return result.scalar_one()


# ---------------------------------------------------------------------------
# Seeds
# ---------------------------------------------------------------------------


async def save_seeds(db: AsyncSession, season_id: int, seeds: dict[int, int]) -> None:
    """seeds = {book_id: seed_number}"""
    for book_id, seed_num in seeds.items():
        seed = Seed(season_id=season_id, book_id=book_id, seed=seed_num)
        db.add(seed)
    await db.commit()


async def get_seeds_for_season(db: AsyncSession, season_id: int) -> list[Seed]:
    result = await db.execute(
        select(Seed)
        .where(Seed.season_id == season_id)
        .options(selectinload(Seed.book))
        .order_by(Seed.seed)
    )
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Bracket matchups
# ---------------------------------------------------------------------------


async def create_matchups(db: AsyncSession, matchups: list[dict]) -> list[BracketMatchup]:
    """matchups = list of {season_id, round, position, book_a_id, book_b_id}"""
    created = []
    for m in matchups:
        matchup = BracketMatchup(**m)
        db.add(matchup)
        created.append(matchup)
    await db.commit()
    return created


async def get_matchups_for_season(db: AsyncSession, season_id: int) -> list[BracketMatchup]:
    result = await db.execute(
        select(BracketMatchup)
        .where(BracketMatchup.season_id == season_id)
        .options(
            selectinload(BracketMatchup.book_a),
            selectinload(BracketMatchup.book_b),
            selectinload(BracketMatchup.winner),
            selectinload(BracketMatchup.votes).selectinload(BracketVote.user),
        )
        .order_by(BracketMatchup.round, BracketMatchup.position)
    )
    return list(result.scalars().all())


async def get_matchup_by_id(db: AsyncSession, matchup_id: int) -> BracketMatchup | None:
    result = await db.execute(
        select(BracketMatchup)
        .where(BracketMatchup.id == matchup_id)
        .options(
            selectinload(BracketMatchup.book_a),
            selectinload(BracketMatchup.book_b),
            selectinload(BracketMatchup.votes),
        )
    )
    return result.scalar_one_or_none()


async def set_matchup_winner(db: AsyncSession, matchup: BracketMatchup, winner_id: int) -> None:
    matchup.winner_id = winner_id
    await db.commit()


async def get_current_bracket_round(db: AsyncSession, season_id: int) -> int:
    """Return the lowest round number that still has undecided matchups."""
    result = await db.execute(
        select(func.min(BracketMatchup.round)).where(
            and_(
                BracketMatchup.season_id == season_id,
                BracketMatchup.winner_id.is_(None),
            )
        )
    )
    val = result.scalar_one_or_none()
    return val or 0


async def get_latest_bracket_round(db: AsyncSession, season_id: int) -> int:
    """Return the highest round number among all matchups for this season."""
    result = await db.execute(
        select(func.max(BracketMatchup.round)).where(
            BracketMatchup.season_id == season_id,
        )
    )
    val = result.scalar_one_or_none()
    return val or 0


async def get_matchups_for_round(
    db: AsyncSession, season_id: int, round_num: int
) -> list[BracketMatchup]:
    result = await db.execute(
        select(BracketMatchup)
        .where(
            and_(
                BracketMatchup.season_id == season_id,
                BracketMatchup.round == round_num,
            )
        )
        .options(
            selectinload(BracketMatchup.book_a),
            selectinload(BracketMatchup.book_b),
            selectinload(BracketMatchup.winner),
            selectinload(BracketMatchup.votes).selectinload(BracketVote.user),
        )
        .order_by(BracketMatchup.position)
    )
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Bracket votes
# ---------------------------------------------------------------------------


async def get_bracket_vote(db: AsyncSession, user_id: int, matchup_id: int) -> BracketVote | None:
    result = await db.execute(
        select(BracketVote).where(
            and_(BracketVote.user_id == user_id, BracketVote.matchup_id == matchup_id)
        )
    )
    return result.scalar_one_or_none()


async def save_bracket_vote(
    db: AsyncSession, user_id: int, matchup_id: int, book_id: int
) -> BracketVote:
    vote = BracketVote(user_id=user_id, matchup_id=matchup_id, book_id=book_id)
    db.add(vote)
    await db.commit()
    await db.refresh(vote)
    return vote


async def count_bracket_voters_for_round(db: AsyncSession, season_id: int, round_num: int) -> int:
    """Number of distinct participants who have voted on ALL real (non-bye) matchups in round."""
    matchup_result = await db.execute(
        select(BracketMatchup.id).where(
            and_(
                BracketMatchup.season_id == season_id,
                BracketMatchup.round == round_num,
                BracketMatchup.book_a_id != BracketMatchup.book_b_id,
            )
        )
    )
    matchup_ids = [row[0] for row in matchup_result.all()]
    if not matchup_ids:
        return 0

    participant_subq = select(SeasonParticipant.user_id).where(
        SeasonParticipant.season_id == season_id
    )
    matchup_count = len(matchup_ids)

    result = await db.execute(
        select(BracketVote.user_id)
        .where(BracketVote.matchup_id.in_(matchup_ids))
        .where(BracketVote.user_id.in_(participant_subq))
        .group_by(BracketVote.user_id)
        .having(func.count(BracketVote.matchup_id) == matchup_count)
    )
    return len(result.all())


# ---------------------------------------------------------------------------
# Veteran tiebreaker
# ---------------------------------------------------------------------------


async def get_prior_nomination_counts(db: AsyncSession, season_id: int) -> dict[int, int]:
    """
    For each book in season_id, count how many times a book with the same
    title+author (case-insensitive) appears in OTHER seasons.
    Returns {book_id: prior_nomination_count}.
    """
    books = await get_books_for_season(db, season_id)
    result: dict[int, int] = {}
    for book in books:
        count_result = await db.execute(
            select(func.count())
            .select_from(Book)
            .where(
                and_(
                    func.lower(Book.title) == book.title.lower(),
                    func.lower(Book.author) == book.author.lower(),
                    Book.season_id != season_id,
                )
            )
        )
        result[book.id] = count_result.scalar_one()
    return result


# ---------------------------------------------------------------------------
# Admin: season / book / user management
# ---------------------------------------------------------------------------


async def delete_season(db: AsyncSession, season_id: int) -> bool:
    """Delete a season and all associated data (cascade order matters)."""
    participants = await db.execute(
        select(SeasonParticipant).where(SeasonParticipant.season_id == season_id)
    )
    for p in participants.scalars().all():
        await db.delete(p)

    matchup_ids_result = await db.execute(
        select(BracketMatchup.id).where(BracketMatchup.season_id == season_id)
    )
    matchup_ids = [row[0] for row in matchup_ids_result.all()]

    if matchup_ids:
        votes = await db.execute(select(BracketVote).where(BracketVote.matchup_id.in_(matchup_ids)))
        for v in votes.scalars().all():
            await db.delete(v)

    matchups = await db.execute(select(BracketMatchup).where(BracketMatchup.season_id == season_id))
    for m in matchups.scalars().all():
        await db.delete(m)

    borda_votes = await db.execute(select(BordaVote).where(BordaVote.season_id == season_id))
    for v in borda_votes.scalars().all():
        await db.delete(v)

    seeds = await db.execute(select(Seed).where(Seed.season_id == season_id))
    for s in seeds.scalars().all():
        await db.delete(s)

    books = await db.execute(select(Book).where(Book.season_id == season_id))
    for b in books.scalars().all():
        await db.delete(b)

    season = await db.execute(select(Season).where(Season.id == season_id))
    s = season.scalar_one_or_none()
    if s is None:
        return False
    await db.delete(s)
    await db.commit()
    return True


async def delete_user(db: AsyncSession, user_id: int, reassign_read_books_to: int) -> bool:
    """Delete a user and cascade their votes/submissions. Reassign their read book entries."""
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        return False

    # Remove season participations
    sps = await db.execute(select(SeasonParticipant).where(SeasonParticipant.user_id == user_id))
    for sp in sps.scalars().all():
        await db.delete(sp)

    # Reassign read books added by this user
    read_books = await db.execute(select(ReadBook).where(ReadBook.added_by == user_id))
    for rb in read_books.scalars().all():
        rb.added_by = reassign_read_books_to

    # Delete bracket votes
    bvotes = await db.execute(select(BracketVote).where(BracketVote.user_id == user_id))
    for v in bvotes.scalars().all():
        await db.delete(v)

    # Delete borda votes
    bovotes = await db.execute(select(BordaVote).where(BordaVote.user_id == user_id))
    for v in bovotes.scalars().all():
        await db.delete(v)

    # Delete submitted books (and their associated votes/seeds)
    user_books = await db.execute(select(Book).where(Book.submitter_id == user_id))
    for book in user_books.scalars().all():
        await _delete_book_data(db, book)

    await db.delete(user)
    await db.commit()
    return True


async def _delete_book_data(db: AsyncSession, book: Book) -> None:
    """Delete all data associated with a book (matchups, votes, seeds), then the book itself."""
    bv = await db.execute(select(BordaVote).where(BordaVote.book_id == book.id))
    for v in bv.scalars().all():
        await db.delete(v)

    seed = await db.execute(select(Seed).where(Seed.book_id == book.id))
    for s in seed.scalars().all():
        await db.delete(s)

    # Delete bracket votes and matchups that reference this book
    from sqlalchemy import or_

    matchup_result = await db.execute(
        select(BracketMatchup).where(
            or_(
                BracketMatchup.book_a_id == book.id,
                BracketMatchup.book_b_id == book.id,
                BracketMatchup.winner_id == book.id,
            )
        )
    )
    for m in matchup_result.scalars().all():
        votes = await db.execute(select(BracketVote).where(BracketVote.matchup_id == m.id))
        for v in votes.scalars().all():
            await db.delete(v)
        await db.delete(m)

    await db.delete(book)


async def create_user(db: AsyncSession, name: str, email: str) -> User:
    """Pre-register a user by name+email (no Google login yet)."""
    user = User(name=name, email=email, google_id=None, is_admin=False)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def update_book(
    db: AsyncSession,
    book_id: int,
    title: str,
    author: str,
    page_count: int,
    description: str | None = None,
) -> Book | None:
    book = (await db.execute(select(Book).where(Book.id == book_id))).scalar_one_or_none()
    if book is None:
        return None
    old_title, old_author = book.title, book.author
    book.title = title
    book.author = author
    book.page_count = page_count
    book.description = description

    # If this book is a season winner, keep the read_books snapshot in sync.
    if old_title != title or old_author != author:
        winner_matchup = (
            (await db.execute(select(BracketMatchup).where(BracketMatchup.winner_id == book_id)))
            .scalars()
            .first()
        )
        if winner_matchup is not None:
            rb = (
                await db.execute(
                    select(ReadBook).where(
                        and_(
                            func.lower(ReadBook.title) == old_title.lower(),
                            func.lower(ReadBook.author) == old_author.lower(),
                            ReadBook.won.is_(True),
                        )
                    )
                )
            ).scalar_one_or_none()
            if rb is not None:
                rb.title = title
                rb.author = author

    await db.commit()
    return book


async def delete_book(db: AsyncSession, book_id: int) -> bool:
    book = (await db.execute(select(Book).where(Book.id == book_id))).scalar_one_or_none()
    if book is None:
        return False
    await _delete_book_data(db, book)
    await db.commit()
    return True


# ---------------------------------------------------------------------------
# "Waiting on" helpers
# ---------------------------------------------------------------------------


async def users_who_havent_submitted(db: AsyncSession, season_id: int) -> list[User]:
    participant_subq = select(SeasonParticipant.user_id).where(
        SeasonParticipant.season_id == season_id
    )
    submitted_subq = select(Book.submitter_id).where(
        Book.season_id == season_id, Book.promoted == False  # noqa: E712
    )
    result = await db.execute(
        select(User)
        .where(User.id.in_(participant_subq))
        .where(User.id.notin_(submitted_subq))
        .order_by(User.name)
    )
    return list(result.scalars().all())


async def users_who_havent_ranked(db: AsyncSession, season_id: int) -> list[User]:
    participant_subq = select(SeasonParticipant.user_id).where(
        SeasonParticipant.season_id == season_id
    )
    ranked_subq = select(BordaVote.user_id.distinct()).where(BordaVote.season_id == season_id)
    result = await db.execute(
        select(User)
        .where(User.id.in_(participant_subq))
        .where(User.id.notin_(ranked_subq))
        .order_by(User.name)
    )
    return list(result.scalars().all())


async def users_who_havent_voted_round(
    db: AsyncSession, season_id: int, round_num: int
) -> list[User]:
    # Only count non-bye matchups (byes require no votes)
    matchup_result = await db.execute(
        select(BracketMatchup.id).where(
            and_(
                BracketMatchup.season_id == season_id,
                BracketMatchup.round == round_num,
                BracketMatchup.book_a_id != BracketMatchup.book_b_id,
            )
        )
    )
    matchup_ids = [row[0] for row in matchup_result.all()]
    if not matchup_ids:
        return []

    participant_subq = select(SeasonParticipant.user_id).where(
        SeasonParticipant.season_id == season_id
    )
    matchup_count = len(matchup_ids)
    voted_all_subq = (
        select(BracketVote.user_id)
        .where(BracketVote.matchup_id.in_(matchup_ids))
        .group_by(BracketVote.user_id)
        .having(func.count(BracketVote.matchup_id) == matchup_count)
    )
    result = await db.execute(
        select(User)
        .where(User.id.in_(participant_subq))
        .where(User.id.notin_(voted_all_subq))
        .order_by(User.name)
    )
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Feature ideas
# ---------------------------------------------------------------------------


async def get_all_ideas(db: AsyncSession) -> list[FeatureIdea]:
    result = await db.execute(
        select(FeatureIdea)
        .options(selectinload(FeatureIdea.upvotes), selectinload(FeatureIdea.author))
        .order_by(FeatureIdea.created_at.desc())
    )
    ideas = list(result.scalars().all())
    ideas.sort(key=lambda i: len(i.upvotes), reverse=True)
    return ideas


async def get_active_idea_count_for_user(db: AsyncSession, user_id: int) -> int:
    """Count only proposed/in-progress ideas against the per-user quota."""
    result = await db.execute(
        select(func.count())
        .select_from(FeatureIdea)
        .where(
            FeatureIdea.author_id == user_id,
            FeatureIdea.status.in_([IdeaStatus.proposed, IdeaStatus.in_progress]),
        )
    )
    return result.scalar_one()


async def has_duplicate_idea(db: AsyncSession, author_id: int, title: str) -> bool:
    """Check if the user already submitted an idea with this exact title."""
    result = await db.execute(
        select(func.count())
        .select_from(FeatureIdea)
        .where(FeatureIdea.author_id == author_id, FeatureIdea.title == title)
    )
    return result.scalar_one() > 0


async def create_idea(
    db: AsyncSession, author_id: int, title: str, description: str, complexity: str | None
) -> FeatureIdea:
    idea = FeatureIdea(
        author_id=author_id, title=title, description=description, complexity=complexity
    )
    db.add(idea)
    await db.commit()
    await db.refresh(idea)
    return idea


async def toggle_upvote(db: AsyncSession, idea_id: int, user_id: int) -> bool:
    """Toggle upvote. Returns True if upvote was added, False if removed."""
    result = await db.execute(
        select(IdeaUpvote).where(IdeaUpvote.idea_id == idea_id, IdeaUpvote.user_id == user_id)
    )
    existing = result.scalar_one_or_none()
    if existing:
        await db.delete(existing)
        await db.commit()
        return False
    db.add(IdeaUpvote(idea_id=idea_id, user_id=user_id))
    await db.commit()
    return True


async def delete_idea(db: AsyncSession, idea_id: int) -> bool:
    result = await db.execute(select(FeatureIdea).where(FeatureIdea.id == idea_id))
    idea = result.scalar_one_or_none()
    if idea is None:
        return False
    await db.delete(idea)
    await db.commit()
    return True


async def update_idea_status(
    db: AsyncSession, idea_id: int, status: IdeaStatus, admin_note: str | None
) -> bool:
    result = await db.execute(select(FeatureIdea).where(FeatureIdea.id == idea_id))
    idea = result.scalar_one_or_none()
    if idea is None:
        return False
    idea.status = status
    idea.admin_note = admin_note or None
    await db.commit()
    return True


async def get_user_upvoted_idea_ids(db: AsyncSession, user_id: int) -> set[int]:
    result = await db.execute(select(IdeaUpvote.idea_id).where(IdeaUpvote.user_id == user_id))
    return set(result.scalars().all())


# ---------------------------------------------------------------------------
# Member stats (admin-only)
# ---------------------------------------------------------------------------


async def get_books_by_user(db: AsyncSession, user_id: int) -> list[Book]:
    result = await db.execute(
        select(Book)
        .where(Book.submitter_id == user_id)
        .options(selectinload(Book.season))
        .order_by(Book.submitted_at.desc())
    )
    return list(result.scalars().all())


async def get_resubmittable_books(
    db: AsyncSession, user_id: int, current_season_id: int
) -> list[Book]:
    """Past submissions by this user that aren't blocked (not in read_books table)."""
    read_books = await get_all_read_books(db)
    blocked_titles = {(rb.title.lower(), rb.author.lower()) for rb in read_books}

    result = await db.execute(
        select(Book)
        .where(Book.submitter_id == user_id, Book.season_id != current_season_id)
        .order_by(Book.submitted_at.desc())
    )
    books = list(result.scalars().all())

    # Dedupe by title+author (keep most recent) and exclude blocked
    seen: set[tuple[str, str]] = set()
    resubmittable = []
    for book in books:
        key = (book.title.lower(), book.author.lower())
        if key in seen or key in blocked_titles:
            continue
        seen.add(key)
        resubmittable.append(book)
    return resubmittable


async def get_season_count_for_user(db: AsyncSession, user_id: int) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(SeasonParticipant)
        .where(SeasonParticipant.user_id == user_id)
    )
    return result.scalar_one()


async def get_winning_book_ids(db: AsyncSession) -> set[int]:
    """Return the set of book IDs that won their season's bracket."""
    subq = (
        select(
            BracketMatchup.season_id,
            func.max(BracketMatchup.round).label("max_round"),
        )
        .group_by(BracketMatchup.season_id)
        .subquery()
    )
    result = await db.execute(
        select(BracketMatchup.winner_id)
        .join(
            subq,
            and_(
                BracketMatchup.season_id == subq.c.season_id,
                BracketMatchup.round == subq.c.max_round,
            ),
        )
        .where(BracketMatchup.winner_id.isnot(None))
    )
    return set(result.scalars().all())


async def get_bracket_vote_accuracy(db: AsyncSession, user_id: int) -> tuple[int, int]:
    """Return (correct_votes, total_resolved_votes) for bracket voting accuracy."""
    result = await db.execute(
        select(BracketVote.book_id, BracketMatchup.winner_id)
        .join(BracketMatchup, BracketVote.matchup_id == BracketMatchup.id)
        .where(
            BracketVote.user_id == user_id,
            BracketMatchup.winner_id.isnot(None),
            BracketMatchup.book_a_id != BracketMatchup.book_b_id,
        )
    )
    rows = result.all()
    total = len(rows)
    correct = sum(1 for vote_book, winner in rows if vote_book == winner)
    return correct, total


# ---------------------------------------------------------------------------
# Meetups
# ---------------------------------------------------------------------------


async def create_meetup(db: AsyncSession, season_id: int, deadline: datetime) -> Meetup:
    meetup = Meetup(season_id=season_id, deadline=deadline)
    db.add(meetup)
    await db.commit()
    await db.refresh(meetup)
    return meetup


async def get_active_meetup(db: AsyncSession) -> Meetup | None:
    """Get the meetup for the most recently completed season, with options+votes loaded."""
    result = await db.execute(
        select(Meetup)
        .join(Season, Meetup.season_id == Season.id)
        .where(Season.state == SeasonState.complete)
        .options(
            selectinload(Meetup.options).selectinload(MeetupOption.votes),
            selectinload(Meetup.options).selectinload(MeetupOption.proposer),
            selectinload(Meetup.season),
        )
        .order_by(Season.created_at.desc())
    )
    meetup = result.scalars().first()
    if meetup and meetup.finalized_option_id:
        # Manually resolve finalized option from the already-loaded options list
        meetup.finalized_option = next(
            (o for o in meetup.options if o.id == meetup.finalized_option_id), None
        )
    elif meetup:
        meetup.finalized_option = None
    return meetup


async def get_active_meetup_shallow(db: AsyncSession) -> Meetup | None:
    """Get the meetup for the most recently completed season (no eager-loaded votes).

    Use this in write routes to avoid loading votes into the session,
    which prevents cascade interference during vote toggle/delete operations.
    """
    result = await db.execute(
        select(Meetup)
        .join(Season, Meetup.season_id == Season.id)
        .where(Season.state == SeasonState.complete)
        .order_by(Season.created_at.desc())
    )
    return result.scalars().first()


async def option_belongs_to_meetup(db: AsyncSession, option_id: int, meetup_id: int) -> bool:
    result = await db.execute(
        select(func.count())
        .select_from(MeetupOption)
        .where(MeetupOption.id == option_id, MeetupOption.meetup_id == meetup_id)
    )
    return result.scalar_one() > 0


async def is_meetup_option_votable(db: AsyncSession, option_id: int) -> bool:
    """Check if option belongs to an active, open, non-finalized meetup.

    Pure scalar query — loads no ORM objects into the session.
    """
    result = await db.execute(
        select(func.count())
        .select_from(MeetupOption)
        .join(Meetup, MeetupOption.meetup_id == Meetup.id)
        .join(Season, Meetup.season_id == Season.id)
        .where(
            MeetupOption.id == option_id,
            Season.state == SeasonState.complete,
            Meetup.finalized_option_id.is_(None),
            Meetup.deadline > func.now(),
        )
    )
    return result.scalar_one() > 0


async def create_meetup_option(
    db: AsyncSession,
    meetup_id: int,
    proposed_by: int,
    event_datetime: datetime,
    location: str,
) -> MeetupOption:
    option = MeetupOption(
        meetup_id=meetup_id,
        proposed_by=proposed_by,
        event_datetime=event_datetime,
        location=location,
    )
    db.add(option)
    await db.commit()
    await db.refresh(option)
    return option


async def delete_meetup_option(db: AsyncSession, option_id: int, user_id: int) -> bool:
    """Delete own option, only if no votes from other users."""
    result = await db.execute(
        select(MeetupOption)
        .where(MeetupOption.id == option_id)
        .options(selectinload(MeetupOption.votes))
    )
    option = result.scalar_one_or_none()
    if option is None or option.proposed_by != user_id:
        return False
    other_votes = [v for v in option.votes if v.user_id != user_id]
    if other_votes:
        return False
    await db.delete(option)
    await db.commit()
    return True


async def toggle_meetup_vote(db: AsyncSession, option_id: int, user_id: int) -> bool:
    """Toggle vote. Returns True if added, False if removed.

    Uses raw DML (INSERT/DELETE) instead of ORM objects to avoid
    cascade/relationship interference when other votes are in the session.
    """
    from sqlalchemy import delete, insert

    # Check existence via scalar count — no ORM objects loaded
    result = await db.execute(
        select(func.count())
        .select_from(MeetupVote)
        .where(MeetupVote.option_id == option_id, MeetupVote.user_id == user_id)
    )
    exists = result.scalar_one() > 0

    if exists:
        await db.execute(
            delete(MeetupVote).where(
                MeetupVote.option_id == option_id, MeetupVote.user_id == user_id
            )
        )
        await db.commit()
        return False
    await db.execute(insert(MeetupVote).values(option_id=option_id, user_id=user_id))
    await db.commit()
    return True


async def finalize_meetup(db: AsyncSession, meetup: Meetup) -> MeetupOption | None:
    """Finalize by picking top-voted option (ties: earliest created_at)."""
    if not meetup.options:
        return None
    best = max(
        meetup.options,
        key=lambda o: (len(o.votes), -o.created_at.timestamp()),
    )
    if not best.votes:
        return None
    meetup.finalized_option_id = best.id
    await db.commit()
    return best


async def admin_finalize_meetup(db: AsyncSession, meetup: Meetup, option_id: int) -> None:
    meetup.finalized_option_id = option_id
    await db.commit()


async def update_meetup_deadline(db: AsyncSession, meetup: Meetup, new_deadline: datetime) -> None:
    meetup.deadline = new_deadline
    await db.commit()
