"""Unit tests for fuzzy duplicate-detection thresholds.

These tests document exactly what edit distances are blocked vs allowed,
making the tuning policy easy to understand and adjust.

Edit-distance thresholds (see crud._TITLE_FUZZ_MAX / _AUTHOR_FUZZ_MAX):
  title  : <= 2 edits blocked
  author : <= 3 edits blocked
Both must match for a block — a different author protects a similar title.
"""

from app.crud import _author_matches, _title_matches

# ---------------------------------------------------------------------------
# Title matching
# ---------------------------------------------------------------------------


def test_title_exact_match():
    assert _title_matches("Dune", "Dune")


def test_title_case_insensitive():
    assert _title_matches("dune", "Dune")
    assert _title_matches("DUNE", "dune")


def test_title_1_edit_blocked():
    # 1 substitution
    assert _title_matches("Dune", "Done")
    # 1 insertion
    assert _title_matches("Dune", "Dunes")
    # 1 deletion
    assert _title_matches("Bloodchild", "Bloodchil")


def test_title_2_edits_blocked():
    # 2 substitutions
    assert _title_matches("Kindred", "Kindret")  # 1 sub
    assert _title_matches("Bloodchild", "Bl00dchild")  # 2 subs


def test_title_3_edits_allowed():
    # 3 edits → NOT blocked (edit distance 3 > threshold 2)
    assert not _title_matches("Kindred", "Kindest")  # 3 subs (r→e, e→s, d→t)
    assert not _title_matches("Dune", "Core")  # 3 subs (D→C, u→o, n→r)


def test_title_clearly_different():
    assert not _title_matches("Dune", "The Road")
    assert not _title_matches("Kindred", "Parable of the Sower")


# ---------------------------------------------------------------------------
# Author matching
# ---------------------------------------------------------------------------


def test_author_exact_match():
    assert _author_matches("Octavia Butler", "Octavia Butler")


def test_author_case_insensitive():
    assert _author_matches("octavia butler", "Octavia Butler")


def test_author_1_edit_blocked():
    assert _author_matches("Octavia Butler", "Octavia Butlor")  # 1 sub


def test_author_middle_initial_blocked():
    # "Octavia E. Butler" → "Octavia Butler" = 3 edits (delete " E.")
    assert _author_matches("Octavia Butler", "Octavia E. Butler")
    assert _author_matches("Ursula K. Le Guin", "Ursula Le Guin")  # 3 edits


def test_author_3_edits_blocked():
    # exactly at threshold
    assert _author_matches("Frank Herbert", "Frank Herburt")  # 2 subs — blocked


def test_author_4_edits_allowed():
    # "Cormac McCarthy" vs "C. McCarthy" = abbreviating first name (> 3 edits)
    assert not _author_matches("Cormac McCarthy", "C. McCarthy")


def test_author_clearly_different():
    assert not _author_matches("Octavia Butler", "Cormac McCarthy")
    assert not _author_matches("Frank Herbert", "Ursula K. Le Guin")


# ---------------------------------------------------------------------------
# Combined: both must match to block
# ---------------------------------------------------------------------------


def test_similar_title_different_author_allowed():
    # "Dune" vs "Dunes" (1 edit) but completely different author → should NOT block
    assert _title_matches("Dune", "Dunes")
    assert not _author_matches("Frank Herbert", "Ursula K. Le Guin")
    # (the combined check in is_book_blocked requires BOTH to match)


def test_different_title_similar_author_allowed():
    # Same author, different books
    assert not _title_matches("Kindred", "Parable of the Sower")
    assert _author_matches("Octavia Butler", "Octavia E. Butler")
    # (the combined check in is_book_blocked requires BOTH to match)


# ---------------------------------------------------------------------------
# Punctuation variants — apostrophes and hyphens (1 edit each → blocked)
# ---------------------------------------------------------------------------


def test_missing_apostrophe_in_title_blocked():
    # distance 1 (delete apostrophe)
    assert _title_matches("Ender's Game", "Enders Game")
    assert _title_matches("Cat's Cradle", "Cats Cradle")
    assert _title_matches("The Handmaid's Tale", "The Handmaids Tale")


def test_hyphen_vs_space_in_title_blocked():
    # distance 1 (hyphen → space substitution)
    assert _title_matches("Slaughterhouse-Five", "Slaughterhouse Five")


# ---------------------------------------------------------------------------
# Accent / diacritic characters (each accented char is 1 substitution)
# ---------------------------------------------------------------------------


def test_accented_author_blocked():
    # "García Márquez" vs "Garcia Marquez" — 2 subs (á→a, á→a)
    assert _author_matches("Gabriel García Márquez", "Gabriel Garcia Marquez")
    assert _author_matches("García Márquez", "Garcia Marquez")


# ---------------------------------------------------------------------------
# Author name formatting — initials and dots
# ---------------------------------------------------------------------------


def test_author_dots_in_initials_blocked():
    # "N.K. Jemisin" vs "NK Jemisin" — 2 deletions (two dots)
    assert _author_matches("N.K. Jemisin", "NK Jemisin")


def test_author_no_space_between_parts_blocked():
    # "Ursula K. Le Guin" vs "Ursula K LeGuin" — 2 edits (delete ".", delete space)
    assert _author_matches("Ursula K. Le Guin", "Ursula K LeGuin")


def test_author_real_name_vs_pen_name_allowed():
    # "N.K. Jemisin" (pen name) vs "Nora K. Jemisin" (real name) — 4 edits → allowed
    # Correct: these look different enough to treat as distinct inputs
    assert not _author_matches("N.K. Jemisin", "Nora K. Jemisin")


# ---------------------------------------------------------------------------
# Typos with real author names
# ---------------------------------------------------------------------------


def test_author_1_char_typo_blocked():
    # Common fat-finger typos
    assert _author_matches("Margaret Atwood", "Margret Atwood")  # distance 1
    assert _author_matches("Douglas Adams", "Douglas Adam")  # distance 1 (missing s)
    assert _author_matches("Donna Tartt", "Donna Tart")  # distance 1 (missing t)


# ---------------------------------------------------------------------------
# Same series, different books — title is different enough to allow
# ---------------------------------------------------------------------------


def test_series_books_not_blocked():
    # "Parable of the Sower" vs "Parable of the Talents" — distance 6
    assert not _title_matches("Parable of the Sower", "Parable of the Talents")
    # "The Fifth Season" vs "The Obelisk Gate" (same trilogy) — clearly different
    assert not _title_matches("The Fifth Season", "The Obelisk Gate")
    # "Dune" vs "Dune Messiah" — distance 8 (insert " Messiah")
    assert not _title_matches("Dune", "Dune Messiah")


# ---------------------------------------------------------------------------
# Known limitations — gaps the fuzzy matching won't catch
# ---------------------------------------------------------------------------


def test_leading_article_not_caught():
    # "The " prefix = 4 edits (exceeds title threshold of 2) → slips through
    # Limitation: "The Left Hand of Darkness" and "Left Hand of Darkness" are the same book
    assert not _title_matches("The Left Hand of Darkness", "Left Hand of Darkness")
    # Same gap for "The Hitchhiker's Guide..."
    assert not _title_matches(
        "The Hitchhiker's Guide to the Galaxy", "Hitchhiker's Guide to the Galaxy"
    )


def test_jr_suffix_not_caught():
    # "Kurt Vonnegut Jr." vs "Kurt Vonnegut" — 4 edits (delete " Jr.") → slips through
    # Limitation: Jr./Sr. suffix beyond the author threshold
    assert not _author_matches("Kurt Vonnegut Jr.", "Kurt Vonnegut")


def test_numeric_vs_written_title_not_caught():
    # "One Hundred Years of Solitude" vs "100 Years of Solitude" — distance 11
    # No fuzzy matching can bridge this; consistent admin entry is the fix
    assert not _title_matches("One Hundred Years of Solitude", "100 Years of Solitude")
