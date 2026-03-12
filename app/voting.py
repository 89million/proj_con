"""Borda count, bracket seeding, and tiebreaker logic."""
from collections import defaultdict
from datetime import datetime

from app.models import Book, BordaVote, BracketMatchup, BracketVote


def compute_borda_seeds(
    books: list[Book],
    votes: list[BordaVote],
) -> dict[int, int]:
    """
    Compute seeds (1 = best) from Borda votes.

    Scoring: if there are N books, a book ranked 1st gets N-1 points,
    ranked 2nd gets N-2, ..., ranked last gets 0.

    Tiebreaker: among books with equal Borda points, the one submitted
    FIRST (earliest submitted_at) gets the better (lower) seed.

    Returns {book_id: seed_number}.
    """
    n = len(books)
    scores: dict[int, int] = defaultdict(int)

    for vote in votes:
        scores[vote.book_id] += (n - vote.rank)

    sorted_books = sorted(
        books,
        key=lambda b: (-scores[b.id], b.submitted_at),
    )

    return {book.id: seed for seed, book in enumerate(sorted_books, start=1)}


def _next_power_of_2(n: int) -> int:
    p = 1
    while p < n:
        p *= 2
    return p


def _build_round_matchups(
    season_id: int,
    round_num: int,
    ordered_book_ids: list[int],
) -> list[dict]:
    """
    Build matchups for one round given an ordered list of book IDs (best first).

    Top seeds get byes when the count is not a power of 2. Byes are stored as
    matchups where book_a == book_b with winner_id pre-set, so they auto-resolve
    without requiring any votes.

    Real matchups pair: position 1 vs position N, 2 vs N-1, etc.
    """
    n = len(ordered_book_ids)
    if n < 2:
        return []

    total_slots = _next_power_of_2(n)
    num_byes = total_slots - n

    matchups = []
    position = 1

    # Top num_byes entries get byes (auto-resolved, no voting needed)
    for i in range(num_byes):
        book_id = ordered_book_ids[i]
        matchups.append({
            "season_id": season_id,
            "round": round_num,
            "position": position,
            "book_a_id": book_id,
            "book_b_id": book_id,
            "winner_id": book_id,
        })
        position += 1

    # Pair remaining entries: top vs bottom
    remaining = ordered_book_ids[num_byes:]
    half = len(remaining) // 2
    for i in range(half):
        matchups.append({
            "season_id": season_id,
            "round": round_num,
            "position": position,
            "book_a_id": remaining[i],
            "book_b_id": remaining[-(i + 1)],
        })
        position += 1

    return matchups


def build_first_round_matchups(
    season_id: int,
    seed_map: dict[int, int],  # {book_id: seed}
) -> list[dict]:
    """Build round-1 matchups from seed assignments."""
    by_seed = {seed: book_id for book_id, seed in seed_map.items()}
    ordered = [by_seed[s] for s in sorted(by_seed)]
    return _build_round_matchups(season_id, 1, ordered)


def build_next_round_matchups(
    season_id: int,
    completed_matchups: list[BracketMatchup],
    next_round: int,
) -> list[dict]:
    """
    Build next-round matchups from the completed matchups of the previous round.

    Winners are ordered by their matchup position, then paired top vs bottom.
    """
    ordered = sorted(completed_matchups, key=lambda m: m.position)
    winners = [m.winner_id for m in ordered]
    return _build_round_matchups(season_id, next_round, winners)


def resolve_matchup_winner(
    matchup: BracketMatchup,
    votes: list[BracketVote],
) -> int:
    """
    Count votes and return the winning book_id.

    Tiebreaker: if vote counts are equal, the book that received its FIRST
    vote earliest wins.
    """
    vote_counts: dict[int, int] = defaultdict(int)
    first_vote_time: dict[int, datetime] = {}

    for vote in votes:
        vote_counts[vote.book_id] += 1
        if vote.book_id not in first_vote_time or vote.voted_at < first_vote_time[vote.book_id]:
            first_vote_time[vote.book_id] = vote.voted_at

    book_a_id = matchup.book_a_id
    book_b_id = matchup.book_b_id

    a_count = vote_counts[book_a_id]
    b_count = vote_counts[book_b_id]

    if a_count > b_count:
        return book_a_id
    if b_count > a_count:
        return book_b_id

    # Tie: earliest first vote wins
    a_time = first_vote_time.get(book_a_id, datetime.max)
    b_time = first_vote_time.get(book_b_id, datetime.max)

    return book_a_id if a_time <= b_time else book_b_id
