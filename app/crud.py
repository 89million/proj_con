"""All database read/write operations."""

from rapidfuzz.distance import Levenshtein
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    Book,
    BordaVote,
    BracketMatchup,
    BracketVote,
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
    """Return the most recent non-complete season, or None."""
    result = await db.execute(
        select(Season)
        .where(Season.state != SeasonState.complete)
        .order_by(Season.created_at.desc())
        .limit(1)
    )
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
    result = await db.execute(
        select(Book).where(and_(Book.submitter_id == user_id, Book.season_id == season_id))
    )
    return result.scalar_one_or_none()


async def create_book(
    db: AsyncSession,
    title: str,
    author: str,
    page_count: int,
    submitter_id: int,
    season_id: int,
) -> Book:
    book = Book(
        title=title,
        author=author,
        page_count=page_count,
        submitter_id=submitter_id,
        season_id=season_id,
    )
    db.add(book)
    await db.commit()
    await db.refresh(book)
    return book


async def count_submissions(db: AsyncSession, season_id: int) -> int:
    result = await db.execute(
        select(func.count()).select_from(Book).where(Book.season_id == season_id)
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
    """Delete all data associated with a book (votes, seeds), then the book itself."""
    bv = await db.execute(select(BordaVote).where(BordaVote.book_id == book.id))
    for v in bv.scalars().all():
        await db.delete(v)

    seed = await db.execute(select(Seed).where(Seed.book_id == book.id))
    for s in seed.scalars().all():
        await db.delete(s)

    await db.delete(book)


async def create_user(db: AsyncSession, name: str, email: str) -> User:
    """Pre-register a user by name+email (no Google login yet)."""
    user = User(name=name, email=email, google_id=None, is_admin=False)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def update_book(
    db: AsyncSession, book_id: int, title: str, author: str, page_count: int
) -> Book | None:
    book = (await db.execute(select(Book).where(Book.id == book_id))).scalar_one_or_none()
    if book is None:
        return None
    book.title = title
    book.author = author
    book.page_count = page_count
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
    submitted_subq = select(Book.submitter_id).where(Book.season_id == season_id)
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
