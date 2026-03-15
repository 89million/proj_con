"""Unit tests for matchup_tiebreaker() and seed_tiebreakers() helpers."""

from datetime import datetime
from unittest.mock import MagicMock

from app.main import matchup_tiebreaker, seed_tiebreakers

# ---------------------------------------------------------------------------
# Helpers to build lightweight fakes
# ---------------------------------------------------------------------------


def _vote(book_id: int, voted_at: datetime | None = None) -> MagicMock:
    v = MagicMock()
    v.book_id = book_id
    v.voted_at = voted_at or datetime(2024, 1, 1)
    return v


def _matchup(
    book_a_id: int,
    book_b_id: int,
    winner_id: int | None,
    votes: list,
) -> MagicMock:
    m = MagicMock()
    m.book_a_id = book_a_id
    m.book_b_id = book_b_id
    m.winner_id = winner_id
    m.votes = votes
    return m


def _seed(book_id: int, seed: int = 1) -> MagicMock:
    s = MagicMock()
    s.book_id = book_id
    s.seed = seed
    return s


# ---------------------------------------------------------------------------
# matchup_tiebreaker — no tie
# ---------------------------------------------------------------------------


def test_matchup_tiebreaker_clear_winner_returns_none():
    """Unambiguous vote majority → no tiebreaker."""
    m = _matchup(1, 2, 1, [_vote(1), _vote(1), _vote(2)])
    assert matchup_tiebreaker(m, {}) is None


def test_matchup_tiebreaker_no_votes_returns_none():
    """Force-advanced matchup with no votes → no tiebreaker."""
    m = _matchup(1, 2, 1, [])
    assert matchup_tiebreaker(m, {}) is None


def test_matchup_tiebreaker_not_yet_resolved_returns_none():
    """winner_id=None (still open) → no tiebreaker."""
    m = _matchup(1, 2, None, [_vote(1)])
    assert matchup_tiebreaker(m, {}) is None


# ---------------------------------------------------------------------------
# matchup_tiebreaker — veteran tiebreak
# ---------------------------------------------------------------------------


def test_matchup_tiebreaker_tie_veteran_wins():
    """Equal votes + unequal prior nominations → 'veteran'."""
    m = _matchup(1, 2, 1, [_vote(1), _vote(2)])
    assert matchup_tiebreaker(m, {1: 3, 2: 1}) == "veteran"


def test_matchup_tiebreaker_tie_veteran_both_zero_noms():
    """Equal votes + both have 0 prior nominations → not 'veteran'."""
    m = _matchup(1, 2, 1, [_vote(1), _vote(2)])
    assert matchup_tiebreaker(m, {}) != "veteran"


# ---------------------------------------------------------------------------
# matchup_tiebreaker — first-vote tiebreak
# ---------------------------------------------------------------------------


def test_matchup_tiebreaker_tie_first_vote():
    """Equal votes + equal prior nominations → 'first_vote'."""
    m = _matchup(1, 2, 1, [_vote(1), _vote(2)])
    assert matchup_tiebreaker(m, {1: 2, 2: 2}) == "first_vote"


def test_matchup_tiebreaker_tie_both_zero_noms_first_vote():
    """Equal votes + no prior nominations at all → 'first_vote'."""
    m = _matchup(1, 2, 1, [_vote(1), _vote(2)])
    assert matchup_tiebreaker(m, {}) == "first_vote"


# ---------------------------------------------------------------------------
# seed_tiebreakers — no tie
# ---------------------------------------------------------------------------


def test_seed_tiebreakers_all_unique_scores():
    """All books have distinct Borda scores → every entry is None."""
    seeds = [_seed(1, 1), _seed(2, 2), _seed(3, 3)]
    scores = {1: 10, 2: 7, 3: 3}
    result = seed_tiebreakers(seeds, scores, {})
    assert result == {1: None, 2: None, 3: None}


# ---------------------------------------------------------------------------
# seed_tiebreakers — veteran tiebreak
# ---------------------------------------------------------------------------


def test_seed_tiebreakers_tie_broken_by_veteran():
    """Two books with equal Borda points, one with more prior nominations → 'veteran'.

    Only the tiebreak winner (lowest seed number) shows the badge.
    """
    seeds = [_seed(1, 1), _seed(2, 2), _seed(3, 3)]
    scores = {1: 10, 2: 10, 3: 4}  # 1 and 2 are tied; book_id=1 has seed #1 (wins)
    noms = {1: 3, 2: 1, 3: 0}
    result = seed_tiebreakers(seeds, scores, noms)
    assert result[1] == "veteran"  # seed #1 — won the tiebreak
    assert result[2] is None  # seed #2 — lost the tiebreak, no badge
    assert result[3] is None


# ---------------------------------------------------------------------------
# seed_tiebreakers — submission-order tiebreak
# ---------------------------------------------------------------------------


def test_seed_tiebreakers_tie_broken_by_submission_order():
    """Two books with equal Borda points AND equal prior nominations → 'submission_order'.

    Only the tiebreak winner (seed #1) shows the badge.
    """
    seeds = [_seed(1, 1), _seed(2, 2)]
    scores = {1: 5, 2: 5}
    noms = {1: 2, 2: 2}
    result = seed_tiebreakers(seeds, scores, noms)
    assert result[1] == "submission_order"  # seed #1 — won
    assert result[2] is None  # seed #2 — lost, no badge


def test_seed_tiebreakers_tie_no_noms_submission_order():
    """Equal scores, no prior nominations → falls back to 'submission_order'.

    Only the lower-seeded book (seed #1) shows the badge.
    """
    seeds = [_seed(10, 1), _seed(20, 2)]
    scores = {10: 6, 20: 6}
    result = seed_tiebreakers(seeds, scores, {})
    assert result[10] == "submission_order"  # seed #1 — won
    assert result[20] is None  # seed #2 — lost, no badge


# ---------------------------------------------------------------------------
# seed_tiebreakers — partial tie (some tied, some not)
# ---------------------------------------------------------------------------


def test_seed_tiebreakers_partial_tie():
    """Three books: two tied, one clear — only the tiebreak winner gets a label."""
    seeds = [_seed(1, 1), _seed(2, 2), _seed(3, 3)]
    scores = {1: 8, 2: 8, 3: 2}
    result = seed_tiebreakers(seeds, scores, {})
    assert result[1] == "submission_order"  # seed #1 — won the tiebreak
    assert result[2] is None  # seed #2 — lost the tiebreak
    assert result[3] is None  # clear score, no tiebreak
