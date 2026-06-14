"""Unit tests for the champion's-run builder used on the winner reveal page."""

from types import SimpleNamespace

from app.main import _build_champion_run, build_round_names


def _book(book_id, title):
    return SimpleNamespace(id=book_id, title=title)


def _vote(book_id):
    return SimpleNamespace(book_id=book_id)


def _matchup(rnd, a, b, votes):
    return SimpleNamespace(
        round=rnd,
        book_a_id=a.id,
        book_b_id=b.id,
        book_a=a,
        book_b=b,
        votes=votes,
    )


def test_empty_matchups_returns_empty():
    assert _build_champion_run([], winner_id=1) == []


def test_run_lists_opponents_in_round_order_with_scores():
    champ = _book(1, "Champ")
    foe1 = _book(2, "Foe One")
    foe2 = _book(3, "Foe Two")

    matchups = [
        # Round 1: champ beats foe1 3–1
        _matchup(1, champ, foe1, [_vote(1), _vote(1), _vote(1), _vote(2)]),
        # Round 2 (final): champ beats foe2 4–2 (champ is book_b here)
        _matchup(2, foe2, champ, [_vote(1), _vote(1), _vote(1), _vote(1), _vote(3), _vote(3)]),
    ]

    run = _build_champion_run(matchups, winner_id=1)

    assert [s["opponent"].title for s in run] == ["Foe One", "Foe Two"]
    assert [(s["champ_votes"], s["opp_votes"]) for s in run] == [(3, 1), (4, 2)]
    # Final round uses the shared round-name labels.
    assert run[-1]["round_name"] == build_round_names(2)[2]


def test_byes_are_skipped():
    champ = _book(1, "Champ")
    foe = _book(2, "Foe")

    matchups = [
        # A bye for the champ (book_a == book_b) — not a real win, must be skipped
        _matchup(1, champ, champ, []),
        # Real final win
        _matchup(2, champ, foe, [_vote(1), _vote(2)]),
    ]

    run = _build_champion_run(matchups, winner_id=1)

    assert len(run) == 1
    assert run[0]["opponent"].title == "Foe"
