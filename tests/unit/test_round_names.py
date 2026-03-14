"""Unit tests for build_round_names — dynamic bracket round labeling."""

import pytest

from app.main import build_round_names

# ---------------------------------------------------------------------------
# 2-round bracket (3 books: 1 bye + 2-book matchup in round 1)
# ---------------------------------------------------------------------------


def test_two_round_bracket_final():
    names = build_round_names(2)
    assert names[2] == "Final"


def test_two_round_bracket_round1_is_semifinals():
    names = build_round_names(2)
    assert names[1] == "Semifinals"


def test_two_round_bracket_has_exactly_two_entries():
    assert len(build_round_names(2)) == 2


# ---------------------------------------------------------------------------
# 3-round bracket (standard 8-book bracket)
# ---------------------------------------------------------------------------


def test_three_round_bracket_final():
    names = build_round_names(3)
    assert names[3] == "Final"


def test_three_round_bracket_semifinals():
    names = build_round_names(3)
    assert names[2] == "Semifinals"


def test_three_round_bracket_quarterfinals():
    names = build_round_names(3)
    assert names[1] == "Quarterfinals"


def test_three_round_bracket_has_exactly_three_entries():
    assert len(build_round_names(3)) == 3


# ---------------------------------------------------------------------------
# 4-round bracket (16 books)
# ---------------------------------------------------------------------------


def test_four_round_bracket_final():
    names = build_round_names(4)
    assert names[4] == "Final"


def test_four_round_bracket_semifinals():
    names = build_round_names(4)
    assert names[3] == "Semifinals"


def test_four_round_bracket_quarterfinals():
    names = build_round_names(4)
    assert names[2] == "Quarterfinals"


def test_four_round_bracket_round1_is_round_of_16():
    names = build_round_names(4)
    assert names[1] == "Round of 16"


# ---------------------------------------------------------------------------
# Edge case: 1-round bracket (straight to Final)
# ---------------------------------------------------------------------------


def test_one_round_bracket_is_final():
    names = build_round_names(1)
    assert names[1] == "Final"
    assert len(names) == 1


# ---------------------------------------------------------------------------
# No round number below 1 ever appears
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("max_round", [1, 2, 3, 4])
def test_no_zero_or_negative_round_keys(max_round):
    names = build_round_names(max_round)
    assert all(k >= 1 for k in names)
