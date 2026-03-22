"""Unit tests for app/voting.py — pure logic, no DB required."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from app.voting import (
    _bracket_seeding_order,
    _next_power_of_2,
    build_first_round_matchups,
    build_next_round_matchups,
    compute_borda_seeds,
    resolve_matchup_winner,
)

# ---------------------------------------------------------------------------
# Helpers to build lightweight fake objects without SQLAlchemy
# ---------------------------------------------------------------------------

BASE_TIME = datetime(2026, 1, 1, 12, 0, 0)


def make_book(id, submitted_at=None):
    b = MagicMock()
    b.id = id
    b.submitted_at = submitted_at or BASE_TIME
    return b


def make_vote(book_id, rank, user_id=1):
    v = MagicMock()
    v.book_id = book_id
    v.rank = rank
    v.user_id = user_id
    return v


def make_matchup(id, book_a_id, book_b_id, position=1, winner_id=None):
    m = MagicMock()
    m.id = id
    m.book_a_id = book_a_id
    m.book_b_id = book_b_id
    m.position = position
    m.winner_id = winner_id
    return m


def make_bracket_vote(book_id, voted_at=None):
    v = MagicMock()
    v.book_id = book_id
    v.voted_at = voted_at or BASE_TIME
    return v


# ---------------------------------------------------------------------------
# compute_borda_seeds
# ---------------------------------------------------------------------------


def test_borda_seeds_basic():
    """Book ranked #1 by most voters gets seed 1."""
    books = [make_book(1), make_book(2), make_book(3)]
    votes = [
        # user 1: prefers book 1
        make_vote(book_id=1, rank=1, user_id=1),
        make_vote(book_id=2, rank=2, user_id=1),
        make_vote(book_id=3, rank=3, user_id=1),
        # user 2: also prefers book 1
        make_vote(book_id=1, rank=1, user_id=2),
        make_vote(book_id=2, rank=2, user_id=2),
        make_vote(book_id=3, rank=3, user_id=2),
        # user 3: prefers book 2
        make_vote(book_id=2, rank=1, user_id=3),
        make_vote(book_id=1, rank=2, user_id=3),
        make_vote(book_id=3, rank=3, user_id=3),
    ]
    seeds = compute_borda_seeds(books, votes)
    assert seeds[1] == 1  # book 1 has most Borda points
    assert seeds[2] == 2
    assert seeds[3] == 3


def test_borda_seeds_tiebreak_by_submission_time():
    """When two books tie on points, the one submitted earlier gets the better seed."""
    earlier = BASE_TIME
    later = BASE_TIME + timedelta(hours=1)
    book_a = make_book(1, submitted_at=earlier)
    book_b = make_book(2, submitted_at=later)

    # Each user ranks them opposite → equal Borda points
    votes = [
        make_vote(book_id=1, rank=1, user_id=1),
        make_vote(book_id=2, rank=2, user_id=1),
        make_vote(book_id=2, rank=1, user_id=2),
        make_vote(book_id=1, rank=2, user_id=2),
    ]
    seeds = compute_borda_seeds([book_a, book_b], votes)
    assert seeds[1] == 1  # book_a submitted earlier → seed 1
    assert seeds[2] == 2


def test_borda_seeds_single_book():
    """A single book with no votes gets seed 1."""
    books = [make_book(42)]
    seeds = compute_borda_seeds(books, [])
    assert seeds[42] == 1


# ---------------------------------------------------------------------------
# _next_power_of_2
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "n, expected",
    [
        (1, 1),
        (2, 2),
        (3, 4),
        (4, 4),
        (5, 8),
        (7, 8),
        (8, 8),
        (9, 16),
    ],
)
def test_next_power_of_2(n, expected):
    assert _next_power_of_2(n) == expected


# ---------------------------------------------------------------------------
# _bracket_seeding_order
# ---------------------------------------------------------------------------


def test_bracket_seeding_order_2():
    assert _bracket_seeding_order(2) == [1, 2]


def test_bracket_seeding_order_4():
    assert _bracket_seeding_order(4) == [1, 4, 2, 3]


def test_bracket_seeding_order_8():
    # 1v8, 4v5 in top half; 2v7, 3v6 in bottom half
    assert _bracket_seeding_order(8) == [1, 8, 4, 5, 2, 7, 3, 6]


def test_bracket_seeding_order_16():
    order = _bracket_seeding_order(16)
    # #1 and #2 must be in opposite halves (positions 1-8 vs 9-16)
    assert 1 in order[:8]
    assert 2 in order[8:]
    # Each adjacent pair sums to 17 (n+1)
    for i in range(0, 16, 2):
        assert order[i] + order[i + 1] == 17


# ---------------------------------------------------------------------------
# build_first_round_matchups / _build_round_matchups
# ---------------------------------------------------------------------------


def _seed_map(*book_ids):
    """Build a seed_map where book_ids[0] is seed 1, [1] is seed 2, etc."""
    return {book_id: seed for seed, book_id in enumerate(book_ids, start=1)}


def test_build_round_matchups_2_books():
    seed_map = _seed_map(10, 20)
    matchups = build_first_round_matchups(season_id=1, seed_map=seed_map)
    real = [m for m in matchups if m["book_a_id"] != m["book_b_id"]]
    byes = [m for m in matchups if m["book_a_id"] == m["book_b_id"]]
    assert len(real) == 1
    assert len(byes) == 0
    assert {real[0]["book_a_id"], real[0]["book_b_id"]} == {10, 20}


def test_build_round_matchups_4_books():
    """4 books: no byes, pairs 1v4 and 2v3."""
    seed_map = _seed_map(1, 2, 3, 4)
    matchups = build_first_round_matchups(season_id=1, seed_map=seed_map)
    real = [m for m in matchups if m["book_a_id"] != m["book_b_id"]]
    byes = [m for m in matchups if m["book_a_id"] == m["book_b_id"]]
    assert len(byes) == 0
    assert len(real) == 2
    pairs = [{m["book_a_id"], m["book_b_id"]} for m in real]
    assert {1, 4} in pairs
    assert {2, 3} in pairs


def test_build_round_matchups_3_books():
    """3 books: 1 bye for seed 1, 1 real matchup between seeds 2 and 3."""
    seed_map = _seed_map(1, 2, 3)
    matchups = build_first_round_matchups(season_id=1, seed_map=seed_map)
    byes = [m for m in matchups if m["book_a_id"] == m["book_b_id"]]
    real = [m for m in matchups if m["book_a_id"] != m["book_b_id"]]
    assert len(byes) == 1
    assert byes[0]["book_a_id"] == 1  # seed 1 gets the bye
    assert len(real) == 1
    assert {real[0]["book_a_id"], real[0]["book_b_id"]} == {2, 3}


def test_build_round_matchups_8_books():
    """8 books: no byes, 4 matchups in bracket seeding order."""
    seed_map = _seed_map(1, 2, 3, 4, 5, 6, 7, 8)
    matchups = build_first_round_matchups(season_id=1, seed_map=seed_map)
    real = [m for m in matchups if m["book_a_id"] != m["book_b_id"]]
    byes = [m for m in matchups if m["book_a_id"] == m["book_b_id"]]
    assert len(byes) == 0
    assert len(real) == 4
    pairs = [{m["book_a_id"], m["book_b_id"]} for m in real]
    assert {1, 8} in pairs
    assert {4, 5} in pairs
    assert {2, 7} in pairs
    assert {3, 6} in pairs


def test_build_round_matchups_8_books_bracket_halves():
    """#1 and #2 must be in opposite halves (positions 1-2 vs 3-4)."""
    seed_map = _seed_map(1, 2, 3, 4, 5, 6, 7, 8)
    matchups = build_first_round_matchups(season_id=1, seed_map=seed_map)
    matchups.sort(key=lambda m: m["position"])
    # Top half (positions 1-2): seeds 1,8,4,5
    top_half_books = set()
    for m in matchups[:2]:
        top_half_books.add(m["book_a_id"])
        top_half_books.add(m["book_b_id"])
    # Bottom half (positions 3-4): seeds 2,7,3,6
    bottom_half_books = set()
    for m in matchups[2:]:
        bottom_half_books.add(m["book_a_id"])
        bottom_half_books.add(m["book_b_id"])
    assert 1 in top_half_books
    assert 2 in bottom_half_books
    # They cannot be in the same half
    assert 1 not in bottom_half_books
    assert 2 not in top_half_books


def test_build_round_matchups_7_books():
    """7 books: 1 bye for seed 1, 3 real matchups. #1 and #2 in opposite halves."""
    seed_map = _seed_map(1, 2, 3, 4, 5, 6, 7)
    matchups = build_first_round_matchups(season_id=1, seed_map=seed_map)
    byes = [m for m in matchups if m["book_a_id"] == m["book_b_id"]]
    real = [m for m in matchups if m["book_a_id"] != m["book_b_id"]]
    assert len(byes) == 1
    assert byes[0]["book_a_id"] == 1
    assert len(real) == 3
    # #2 should be in a real matchup in the bottom half, not adjacent to #1's bye
    matchups.sort(key=lambda m: m["position"])
    top_half_ids = set()
    for m in matchups[:2]:
        top_half_ids.update([m["book_a_id"], m["book_b_id"]])
    bottom_half_ids = set()
    for m in matchups[2:]:
        bottom_half_ids.update([m["book_a_id"], m["book_b_id"]])
    assert 1 in top_half_ids
    assert 2 in bottom_half_ids


def test_byes_are_pre_resolved():
    """Bye matchups must have winner_id set at creation time."""
    seed_map = _seed_map(1, 2, 3)  # 3 books → 1 bye
    matchups = build_first_round_matchups(season_id=1, seed_map=seed_map)
    byes = [m for m in matchups if m["book_a_id"] == m["book_b_id"]]
    for bye in byes:
        assert "winner_id" in bye
        assert bye["winner_id"] == bye["book_a_id"]


# ---------------------------------------------------------------------------
# resolve_matchup_winner
# ---------------------------------------------------------------------------


def test_resolve_matchup_winner_clear():
    """Book A gets 3 votes, book B gets 1 — book A wins."""
    matchup = make_matchup(id=1, book_a_id=10, book_b_id=20)
    votes = [
        make_bracket_vote(book_id=10),
        make_bracket_vote(book_id=10),
        make_bracket_vote(book_id=10),
        make_bracket_vote(book_id=20),
    ]
    assert resolve_matchup_winner(matchup, votes) == 10


def test_resolve_matchup_winner_tie_by_first_vote():
    """Equal votes — book whose FIRST vote arrived earliest wins."""
    matchup = make_matchup(id=1, book_a_id=10, book_b_id=20)
    t0 = BASE_TIME
    t1 = BASE_TIME + timedelta(seconds=1)
    t2 = BASE_TIME + timedelta(seconds=2)
    t3 = BASE_TIME + timedelta(seconds=3)

    # book 20 gets its first vote earlier (t0), book 10's first vote is t1
    votes = [
        make_bracket_vote(book_id=20, voted_at=t0),
        make_bracket_vote(book_id=10, voted_at=t1),
        make_bracket_vote(book_id=20, voted_at=t2),
        make_bracket_vote(book_id=10, voted_at=t3),
    ]
    assert resolve_matchup_winner(matchup, votes) == 20


# ---------------------------------------------------------------------------
# build_next_round_matchups
# ---------------------------------------------------------------------------


def test_build_next_round_from_4():
    """4 QF winners → 2 SF matchups, paired by adjacent positions (1v2, 3v4)."""
    # With proper bracket seeding: 1v8, 4v5, 2v7, 3v6
    completed = [
        make_matchup(id=1, book_a_id=1, book_b_id=8, position=1, winner_id=1),
        make_matchup(id=2, book_a_id=4, book_b_id=5, position=2, winner_id=4),
        make_matchup(id=3, book_a_id=2, book_b_id=7, position=3, winner_id=2),
        make_matchup(id=4, book_a_id=3, book_b_id=6, position=4, winner_id=3),
    ]
    matchups = build_next_round_matchups(season_id=1, completed_matchups=completed, next_round=2)
    real = [m for m in matchups if m["book_a_id"] != m["book_b_id"]]
    assert len(real) == 2
    # Adjacent pairing: position 1 winner vs position 2 winner
    assert real[0]["book_a_id"] == 1
    assert real[0]["book_b_id"] == 4
    assert real[0]["position"] == 1
    # Position 3 winner vs position 4 winner
    assert real[1]["book_a_id"] == 2
    assert real[1]["book_b_id"] == 3
    assert real[1]["position"] == 2


def test_build_next_round_from_2():
    """2 SF winners → 1 Final matchup."""
    completed = [
        make_matchup(id=1, book_a_id=1, book_b_id=4, position=1, winner_id=1),
        make_matchup(id=2, book_a_id=2, book_b_id=3, position=2, winner_id=2),
    ]
    matchups = build_next_round_matchups(season_id=1, completed_matchups=completed, next_round=3)
    real = [m for m in matchups if m["book_a_id"] != m["book_b_id"]]
    assert len(real) == 1
    assert real[0]["book_a_id"] == 1
    assert real[0]["book_b_id"] == 2


def test_build_next_round_preserves_bracket_structure():
    """In a standard 8-seed bracket, #1 can only meet #2 in the final."""
    # Round 1 with proper bracket seeding: 1v8, 4v5, 2v7, 3v6
    r1 = [
        make_matchup(id=1, book_a_id=1, book_b_id=8, position=1, winner_id=1),
        make_matchup(id=2, book_a_id=4, book_b_id=5, position=2, winner_id=4),
        make_matchup(id=3, book_a_id=2, book_b_id=7, position=3, winner_id=2),
        make_matchup(id=4, book_a_id=3, book_b_id=6, position=4, winner_id=3),
    ]
    r2 = build_next_round_matchups(season_id=1, completed_matchups=r1, next_round=2)
    # SF1: 1 vs 4 (top half), SF2: 2 vs 3 (bottom half)
    assert r2[0]["book_a_id"] == 1 and r2[0]["book_b_id"] == 4
    assert r2[1]["book_a_id"] == 2 and r2[1]["book_b_id"] == 3
    # #1 and #2 are in opposite semis — can only meet in the final
    sf = [
        make_matchup(id=5, book_a_id=1, book_b_id=4, position=1, winner_id=1),
        make_matchup(id=6, book_a_id=2, book_b_id=3, position=2, winner_id=2),
    ]
    r3 = build_next_round_matchups(season_id=1, completed_matchups=sf, next_round=3)
    # Final: 1 vs 2
    assert r3[0]["book_a_id"] == 1 and r3[0]["book_b_id"] == 2


def test_build_next_round_upsets_stay_in_bracket_half():
    """If lower seeds upset, they stay in their bracket half."""
    # Round 1 with proper seeding: 1v8, 4v5, 2v7, 3v6 — all upsets
    r1 = [
        make_matchup(id=1, book_a_id=1, book_b_id=8, position=1, winner_id=8),
        make_matchup(id=2, book_a_id=4, book_b_id=5, position=2, winner_id=5),
        make_matchup(id=3, book_a_id=2, book_b_id=7, position=3, winner_id=7),
        make_matchup(id=4, book_a_id=3, book_b_id=6, position=4, winner_id=6),
    ]
    r2 = build_next_round_matchups(season_id=1, completed_matchups=r1, next_round=2)
    # SF1: 8 vs 5 (top half), SF2: 7 vs 6 (bottom half)
    assert r2[0]["book_a_id"] == 8 and r2[0]["book_b_id"] == 5
    assert r2[1]["book_a_id"] == 7 and r2[1]["book_b_id"] == 6


def test_build_next_round_odd_winners_bye():
    """Odd number of winners produces a bye in the next round."""
    r1 = [
        make_matchup(id=1, book_a_id=1, book_b_id=6, position=1, winner_id=1),
        make_matchup(id=2, book_a_id=2, book_b_id=5, position=2, winner_id=2),
        make_matchup(id=3, book_a_id=3, book_b_id=4, position=3, winner_id=3),
    ]
    r2 = build_next_round_matchups(season_id=1, completed_matchups=r1, next_round=2)
    assert len(r2) == 2
    # First matchup: 1 vs 2
    assert r2[0]["book_a_id"] == 1 and r2[0]["book_b_id"] == 2
    # Second: bye for winner 3
    assert r2[1]["book_a_id"] == 3 and r2[1]["book_b_id"] == 3
    assert r2[1]["winner_id"] == 3


# ---------------------------------------------------------------------------
# Veteran tiebreaker — prior_nominations
# ---------------------------------------------------------------------------


def test_borda_seeds_tiebreak_by_prior_nominations():
    """When Borda points tie, the book with more prior nominations gets the better seed."""
    book_veteran = make_book(1)
    book_newcomer = make_book(2)

    # Equal Borda points: each user ranks them in opposite order
    votes = [
        make_vote(book_id=1, rank=1, user_id=1),
        make_vote(book_id=2, rank=2, user_id=1),
        make_vote(book_id=2, rank=1, user_id=2),
        make_vote(book_id=1, rank=2, user_id=2),
    ]
    prior = {1: 2, 2: 0}  # book 1 has been nominated twice before
    seeds = compute_borda_seeds([book_veteran, book_newcomer], votes, prior_nominations=prior)
    assert seeds[1] == 1  # veteran gets seed 1
    assert seeds[2] == 2


def test_borda_seeds_prior_nominations_only_breaks_borda_tie():
    """Prior nominations do NOT override a clear Borda points lead."""
    book_a = make_book(1)  # worse Borda score but veteran
    book_b = make_book(2)  # better Borda score but newcomer

    # Both users prefer book_b → book_b wins on Borda points regardless of vet status
    votes = [
        make_vote(book_id=2, rank=1, user_id=1),
        make_vote(book_id=1, rank=2, user_id=1),
        make_vote(book_id=2, rank=1, user_id=2),
        make_vote(book_id=1, rank=2, user_id=2),
    ]
    prior = {1: 5, 2: 0}  # book_a is a heavy veteran, but Borda still decides
    seeds = compute_borda_seeds([book_a, book_b], votes, prior_nominations=prior)
    assert seeds[2] == 1  # higher Borda points wins, vet status doesn't override
    assert seeds[1] == 2


def test_resolve_matchup_winner_tiebreak_by_prior_nominations():
    """Equal votes: book with more prior nominations wins before checking timestamps."""
    matchup = make_matchup(id=1, book_a_id=10, book_b_id=20)
    t0 = BASE_TIME

    # 1 vote each — a tie on vote count
    votes = [
        make_bracket_vote(book_id=10, voted_at=t0),
        make_bracket_vote(book_id=20, voted_at=t0),
    ]
    # book_a (10) is a veteran; book_b (20) has no prior nominations
    prior = {10: 3, 20: 0}
    assert resolve_matchup_winner(matchup, votes, prior_nominations=prior) == 10


def test_resolve_matchup_winner_prior_nominations_dont_override_vote_lead():
    """More votes beats prior nominations."""
    matchup = make_matchup(id=1, book_a_id=10, book_b_id=20)

    # book_b has 3 votes; book_a has only 1 — book_b wins despite book_a being a veteran
    votes = [
        make_bracket_vote(book_id=10),
        make_bracket_vote(book_id=20),
        make_bracket_vote(book_id=20),
        make_bracket_vote(book_id=20),
    ]
    prior = {10: 99, 20: 0}
    assert resolve_matchup_winner(matchup, votes, prior_nominations=prior) == 20
