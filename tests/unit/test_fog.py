"""Unit tests for app.fog — server-side spoiler fog.

The model is deliberately blunt: once a post is even one page ahead of the
reader, every content word is replaced, and it stays that way at any distance.
There is no partial-survival band, so the leak tests are absolutes rather than
rates. Distance is carried entirely by blur.
"""

from app.fog import FULL_FOG_DISTANCE, MAX_BLUR_PX, MIN_BLUR_PX, blur_for, fog_text

SPOILER = (
    "Elizabeth is murdered on the wedding night and Victor finally understands "
    "what the creature meant by the threat in Ingolstadt"
)

# Rare, plot-critical words — the ones that actually matter if they leak.
CONTENT_WORDS = ["Elizabeth", "murdered", "wedding", "Victor", "creature", "Ingolstadt"]


# ---------------------------------------------------------------------------
# Arrived readers get the truth
# ---------------------------------------------------------------------------


def test_distance_zero_returns_text_unchanged():
    assert fog_text(SPOILER, 0, seed=1).plain == SPOILER


def test_negative_distance_returns_text_unchanged():
    """Reading past the anchor is the same as arriving at it."""
    assert fog_text(SPOILER, -40, seed=1).plain == SPOILER


def test_arrived_text_is_not_marked_fogged():
    assert fog_text(SPOILER, 0, seed=1).is_fogged is False


# ---------------------------------------------------------------------------
# The leak test — absolute at every distance
# ---------------------------------------------------------------------------


def test_one_page_ahead_already_drops_every_content_word():
    """A single page of separation is the whole trigger."""
    plain = fog_text(SPOILER, 1, seed=7).plain
    for word in CONTENT_WORDS:
        assert word not in plain


def test_no_content_word_survives_at_any_distance():
    for distance in (1, 2, 5, 20, 60, FULL_FOG_DISTANCE, FULL_FOG_DISTANCE * 5):
        plain = fog_text(SPOILER, distance, seed=distance).plain
        for word in CONTENT_WORDS:
            assert word not in plain, f"{word!r} survived at distance {distance}"


def test_leak_resistance_does_not_depend_on_the_seed():
    for seed in range(1, 60):
        plain = fog_text(SPOILER, 1, seed=seed).plain
        assert not any(w in plain for w in CONTENT_WORDS), f"seed {seed} leaked"


def test_fog_never_returns_the_original_body():
    for distance in (1, 5, 20, 60, FULL_FOG_DISTANCE):
        assert fog_text(SPOILER, distance, seed=2).plain != SPOILER


# ---------------------------------------------------------------------------
# Blur is the only thing that varies with distance
# ---------------------------------------------------------------------------


def test_blur_is_mild_one_page_out():
    assert MIN_BLUR_PX <= fog_text(SPOILER, 1, seed=1).blur_px < 1.0


def test_blur_grows_with_distance():
    blurs = [fog_text(SPOILER, d, seed=5).blur_px for d in (1, 10, 30, 60, FULL_FOG_DISTANCE)]
    assert blurs == sorted(blurs)
    assert blurs[0] < blurs[-1]


def test_blur_tops_out_and_stays_there():
    assert blur_for(FULL_FOG_DISTANCE) == MAX_BLUR_PX
    assert blur_for(FULL_FOG_DISTANCE * 10) == MAX_BLUR_PX


def test_arrived_posts_are_not_blurred():
    assert blur_for(0) == 0.0
    assert fog_text(SPOILER, 0, seed=1).blur_px == 0.0


def test_same_words_are_hidden_near_and_far():
    """Distance changes the blur, not which words are replaced."""
    near = [w for w, fogged in fog_text(SPOILER, 1, seed=3).words if fogged]
    far = [w for w, fogged in fog_text(SPOILER, 200, seed=3).words if fogged]
    assert len(near) == len(far)


# ---------------------------------------------------------------------------
# It still has to look like language
# ---------------------------------------------------------------------------


def test_every_word_is_replaced_including_the_grammar():
    """Leaving function words standing gave the eye a sharp skeleton to read.

    Nothing survives now, so a fogged post has no legible structure to squint
    at — the blur applies to a paragraph that is already entirely invented.
    """
    fogged = fog_text(SPOILER, 50, seed=1)
    kept = {text.lower() for text, is_fogged in fogged.words if not is_fogged}
    assert not kept & {"is", "on", "the", "and", "what", "by", "in"}
    assert all(is_fogged for _, is_fogged in fogged.words)


def test_replacements_keep_the_original_word_length():
    body = "Frankenstein pursued the creature northward"
    fogged = fog_text(body, 40, seed=4)
    for original, (rendered, _) in zip(body.split(), fogged.words):
        assert len(rendered) == len(original)


def test_replacements_are_alphabetic_not_redaction_marks():
    for text, is_fogged in fog_text(SPOILER, 40, seed=9).words:
        if is_fogged:
            assert text.isalpha(), f"{text!r} should read as a word"


def test_capitalisation_is_preserved():
    fogged = fog_text("Elizabeth waited", 40, seed=6)
    assert fogged.words[0][0][0].isupper()


def test_trailing_punctuation_survives():
    fogged = fog_text("The creature spoke, then vanished.", 40, seed=8)
    assert fogged.plain.endswith(".")
    assert "," in fogged.plain


def test_word_count_is_preserved():
    assert len(fog_text(SPOILER, 40, seed=1).words) == len(SPOILER.split())


# ---------------------------------------------------------------------------
# Stability
# ---------------------------------------------------------------------------


def test_same_seed_and_distance_produce_identical_fog():
    """Nonsense must not reshuffle between page loads."""
    assert fog_text(SPOILER, 30, seed=42).plain == fog_text(SPOILER, 30, seed=42).plain


def test_nonsense_does_not_change_as_the_reader_advances():
    """Approaching a post shouldn't rewrite the words underneath it."""
    assert fog_text(SPOILER, 80, seed=11).plain == fog_text(SPOILER, 3, seed=11).plain


def test_different_posts_fog_differently():
    assert fog_text(SPOILER, 30, seed=1).plain != fog_text(SPOILER, 30, seed=2).plain


def test_empty_body_does_not_explode():
    assert fog_text("", 50, seed=1).words == []
