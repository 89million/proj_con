"""Borda count, bracket seeding, and tiebreaker logic."""

from collections import defaultdict
from datetime import datetime

from app.models import Book, BordaVote, BracketMatchup, BracketVote


def compute_borda_seeds(
    books: list[Book],
    votes: list[BordaVote],
    prior_nominations: dict[int, int] | None = None,
) -> dict[int, int]:
    """
    Compute seeds (1 = best) from Borda votes.

    Scoring: if there are N books, a book ranked 1st gets N-1 points,
    ranked 2nd gets N-2, ..., ranked last gets 0.

    Tiebreaker order:
    1. More Borda points → better seed
    2. More prior nominations (veteran books) → better seed
    3. Earlier submitted_at → better seed

    Returns {book_id: seed_number}.
    """
    if prior_nominations is None:
        prior_nominations = {}

    n = len(books)
    scores: dict[int, int] = defaultdict(int)

    for vote in votes:
        scores[vote.book_id] += n - vote.rank

    sorted_books = sorted(
        books,
        key=lambda b: (-scores[b.id], -prior_nominations.get(b.id, 0), b.submitted_at),
    )

    return {book.id: seed for seed, book in enumerate(sorted_books, start=1)}


def get_relegated_book_ids(
    seed_map: dict[int, int], relegate_count: int, min_bracket_size: int = 2
) -> set[int]:
    """Return book IDs of the bottom `relegate_count` seeds (excluded from bracket).

    Returns empty set if relegating would leave fewer than `min_bracket_size` books.
    """
    total = len(seed_map)
    if relegate_count <= 0 or total - relegate_count < min_bracket_size:
        return set()
    sorted_by_seed = sorted(seed_map.items(), key=lambda x: x[1], reverse=True)
    return {book_id for book_id, _ in sorted_by_seed[:relegate_count]}


def _next_power_of_2(n: int) -> int:
    p = 1
    while p < n:
        p *= 2
    return p


def _bracket_seeding_order(n: int) -> list[int]:
    """Standard tournament bracket seeding order for *n* slots (power of 2).

    Returns 1-indexed seeds where adjacent pairs form matchups.
    E.g. n=8 → [1, 8, 4, 5, 2, 7, 3, 6]
      → matchups: 1v8, 4v5, 2v7, 3v6
    This guarantees #1 and #2 are in opposite halves and can only meet in the final.
    """
    order = [1]
    size = 1
    while size < n:
        size *= 2
        new_order = []
        for s in order:
            new_order.append(s)
            new_order.append(size + 1 - s)
        order = new_order
    return order


def _build_round_matchups(
    season_id: int,
    round_num: int,
    ordered_book_ids: list[int],
) -> list[dict]:
    """
    Build matchups for one round given an ordered list of book IDs (best first).

    Uses standard tournament bracket seeding so that #1 and #2 are on opposite
    sides and can only meet in the final. Seeds without a corresponding book
    (when count is not a power of 2) become byes — stored as matchups where
    book_a == book_b with winner_id pre-set.
    """
    n = len(ordered_book_ids)
    if n < 2:
        return []

    total_slots = _next_power_of_2(n)
    seeding = _bracket_seeding_order(total_slots)

    matchups = []
    position = 1

    for i in range(0, total_slots, 2):
        seed_a = seeding[i] - 1  # convert to 0-indexed
        seed_b = seeding[i + 1] - 1

        has_a = seed_a < n
        has_b = seed_b < n

        if has_a and has_b:
            matchups.append(
                {
                    "season_id": season_id,
                    "round": round_num,
                    "position": position,
                    "book_a_id": ordered_book_ids[seed_a],
                    "book_b_id": ordered_book_ids[seed_b],
                }
            )
        elif has_a:
            book_id = ordered_book_ids[seed_a]
            matchups.append(
                {
                    "season_id": season_id,
                    "round": round_num,
                    "position": position,
                    "book_a_id": book_id,
                    "book_b_id": book_id,
                    "winner_id": book_id,
                }
            )
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

    Winners are paired by adjacent positions (1&2, 3&4, …) so the bracket
    structure is preserved — a #1 seed can only meet a #2 seed in the final.
    """
    ordered = sorted(completed_matchups, key=lambda m: m.position)
    winners = [m.winner_id for m in ordered]

    matchups: list[dict] = []
    position = 1
    for i in range(0, len(winners), 2):
        if i + 1 < len(winners):
            matchups.append(
                {
                    "season_id": season_id,
                    "round": next_round,
                    "position": position,
                    "book_a_id": winners[i],
                    "book_b_id": winners[i + 1],
                }
            )
        else:
            # Odd winner count — bye
            matchups.append(
                {
                    "season_id": season_id,
                    "round": next_round,
                    "position": position,
                    "book_a_id": winners[i],
                    "book_b_id": winners[i],
                    "winner_id": winners[i],
                }
            )
        position += 1

    return matchups


def resolve_matchup_winner(
    matchup: BracketMatchup,
    votes: list[BracketVote],
    prior_nominations: dict[int, int] | None = None,
) -> int:
    """
    Count votes and return the winning book_id.

    Tiebreaker order:
    1. More votes → wins
    2. More prior nominations (veteran books) → wins
    3. Earliest first vote (voted_at) → wins
    """
    if prior_nominations is None:
        prior_nominations = {}

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

    # Tie: more prior nominations wins
    a_noms = prior_nominations.get(book_a_id, 0)
    b_noms = prior_nominations.get(book_b_id, 0)
    if a_noms != b_noms:
        return book_a_id if a_noms > b_noms else book_b_id

    # Still tied: earliest first vote wins
    a_time = first_vote_time.get(book_a_id, datetime.max)
    b_time = first_vote_time.get(book_b_id, datetime.max)

    return book_a_id if a_time <= b_time else book_b_id
