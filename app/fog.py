"""Server-side spoiler fog for page-anchored discussion.

A discussion post is anchored to the page it's about. A reader who hasn't got
that far never receives the real words: the server swaps them for generated,
English-shaped nonsense of the same length before the template is rendered, so
the true sentence never leaves the database.

Substitution is all-or-nothing: one page short of the anchor is enough for every
content word to be replaced, and it stays that way however far back the reader
is. There is no partial-survival band, so no content word can ever slip through.

Distance is carried entirely by blur instead — barely there at a page out,
thickening to unreadable far from the anchor.

Two things make it read as distance rather than censorship:

* Replacements are word-shaped — real letters, real syllable structure, same
  length. Nothing is blanked, struck out, or boxed.
* Function words ("the", "and", "was") are left alone. They carry no spoilers
  and keep the sentence's cadence, so it still scans as prose and means nothing.
"""

import math
import re
from dataclasses import dataclass

# Distance at which blur reaches full strength.
FULL_FOG_DISTANCE = 90

# Blur in pixels. A page out should be legible-but-soft so the nonsense can
# actually be seen; far off it becomes unreadable weather. The curve is convex
# so most of the thickening happens in the second half of the range.
MIN_BLUR_PX = 0.3
MAX_BLUR_PX = 4.0
_BLUR_CURVE = 1.15

_ONSET = (
    "b c d f g h l m n p r s t v w br cl cr dr fl gl gr pl pr sh sl sm sn sp st th tr wh"
).split()
_NUCLEUS = "a e i o u ai ea ee ie oa oo ou ow au ei".split()
_CODA = "b ck d f g l ld lt m n nd ng nk nt p r rd rk rn s sh sk st t th".split() + [""]

# Short common words keep the sentence scanning like English, so they get their
# own pool instead of being rebuilt from syllables.
_FAKE_SHORT = (
    "tha ond ith sel pon uth ern ald oth ist ane rue vel ost "
    "ret wen lor esh ade irn oam tul nes har ilt oup dre sen"
).split()

# lead punctuation / the word itself / trailing punctuation
_TOKEN = re.compile(r"^([^A-Za-z]*)([A-Za-z][A-Za-z']*)?(.*)$", re.S)


def _noise(a: float, b: float) -> float:
    """Deterministic pseudo-random value in [0, 1).

    Hash-free so it can't drift between processes or Python versions the way
    hash()-seeded RNG state can.
    """
    x = math.sin(a * 127.1 + b * 311.7) * 43758.5453
    return x - math.floor(x)


def _pick(pool: list[str], seed: float, step: int) -> str:
    return pool[int(_noise(seed * 7.13 + step * 3.77, step + 1) * len(pool)) % len(pool)]


def _fake_word(core: str, seed: int) -> str:
    """Build a pronounceable nonsense word the same length as `core`."""
    length = len(core)
    if length <= 1:
        return core

    if length <= 3:
        out = _pick(_FAKE_SHORT, seed, 0)[:length]
    else:
        out = ""
        step = 0
        while len(out) < length:
            out += _pick(_ONSET, seed, step)
            step += 1
            out += _pick(_NUCLEUS, seed, step)
            step += 1
            if len(out) + 2 <= length:
                out += _pick(_CODA, seed, step)
                step += 1
        out = out[:length]
        # a three-consonant pile-up at the end stops looking like a word
        if re.search(r"[bcdfghjklmnpqrstvwxz]{3}$", out):
            out = out[:-1] + "e"

    if core[:1].isupper():
        out = out[:1].upper() + out[1:]
    return out


def blur_for(distance: int) -> float:
    """How hard to blur a post the reader is `distance` pages short of.

    Substitution already hides the content, so blur's only job is to show how
    far off the post is: a faint softening one page out, unreadable weather by
    FULL_FOG_DISTANCE.
    """
    if distance <= 0:
        return 0.0
    reach = min(1.0, distance / FULL_FOG_DISTANCE) ** _BLUR_CURVE
    return round(MIN_BLUR_PX + (MAX_BLUR_PX - MIN_BLUR_PX) * reach, 2)


# Muttered reactions shown under an unreadable post, picked by how much of it
# the reader can physically make out. They confirm that yes, it is meant to look
# like that, without explaining the rules.
#
# These are the reader's OWN thought, reflected back at them and turned absurd.
# So it's first-person and about the self in this moment — my eyes, my brain,
# my refusal to ask — never "that one" or "it", which point at the post like a
# bystander and read as commentary on some other thing. Same guy underneath:
# he will not admit he can't read it, and he never concedes.
_REMARKS_LEGIBLE = (
    "what the fuck does that mean?",
    "I can read this. I'm reading it right now. Watch me.",
    "Yeah. Yep. Mm-hm. Absolutely. Fully following.",
    "I know all these words. Every single fucking one.",
    "I'm not gonna be the guy who asks. I refuse.",
    "No, this tracks. This tracks completely. I'm tracking.",
    "I speak this. This is a language I personally speak.",
    "Nodding. I'm nodding. That means I get it.",
    "Understood. Deeply. On a level I won't explain.",
)
_REMARKS_STRAINING = (
    "Give me eleven more fucking seconds.",
    "Almost. I've almost got it. Nobody talk to me.",
    "I've got 'the'. I'm building out from 'the'.",
    "Don't help me. Do NOT fucking help me.",
    "I can feel my brain doing it. Holy shit, it's doing it.",
    "One more pass and I'm in. I'm so in.",
    "It's coming to me. It is absolutely coming to me.",
    "I'm gonna get this if it kills me, and it might.",
)
_REMARKS_BLIND = (
    "I can't see shit",
    "I already read this. In my heart. Weeks ago.",
    "My eyes are fine. My eyes are FUCKING fine.",
    "I'm just gonna say I read it and move on with my life.",
    "I've made my peace. I'm at peace. I'm SO fucking peaceful.",
    "Nope. Nothing. And honestly? I'm thriving.",
    "I'll read it in the car. I'll read it never.",
    "I don't need this. I've never needed anything.",
)


def _remark_for(blur_px: float, seed: int) -> str:
    """Pick a stable reaction line for how unreadable this post is."""
    if blur_px < 1.0:
        pool = _REMARKS_LEGIBLE
    elif blur_px < 2.5:
        pool = _REMARKS_STRAINING
    else:
        pool = _REMARKS_BLIND
    return pool[int(_noise(seed, blur_px) * len(pool)) % len(pool)]


@dataclass(frozen=True)
class FoggedText:
    """A post body prepared for one specific reader.

    `words` is a list of (text, is_fogged) pairs — fogged entries hold generated
    nonsense, never the original. `blur_px` and `opacity` drive the CSS so
    distance reads as weather, and `remark` is the aside shown underneath.
    """

    words: list[tuple[str, bool]]
    blur_px: float
    opacity: float
    remark: str = ""

    @property
    def is_fogged(self) -> bool:
        return any(fogged for _, fogged in self.words)

    @property
    def plain(self) -> str:
        """Flat string of what the reader actually gets. Handy in tests."""
        return " ".join(text for text, _ in self.words)


def fog_text(body: str, distance: int, *, seed: int) -> FoggedText:
    """Prepare `body` for a reader `distance` pages short of its anchor.

    `distance <= 0` means the reader has reached the page and gets the real
    text. `seed` should be stable for a given post (its id works) so the
    nonsense doesn't reshuffle on every page load.
    """
    tokens = body.split()

    if distance <= 0:
        return FoggedText([(t, False) for t in tokens], 0.0, 1.0)

    words: list[tuple[str, bool]] = []
    for index, token in enumerate(tokens):
        match = _TOKEN.match(token)
        lead, core, trail = match.group(1), match.group(2) or "", match.group(3)

        # Every word goes. Leaving the grammar standing gave the eye a sharp
        # skeleton to read between the blurred parts, which defeats the point —
        # one page ahead or a hundred, the whole sentence is replaced, and only
        # the blur says how far off it is.
        if not core:
            words.append((token, False))
        else:
            words.append((lead + _fake_word(core, seed * 31 + index) + trail, True))

    reach = min(1.0, distance / FULL_FOG_DISTANCE)
    blur = blur_for(distance)
    return FoggedText(
        words=words,
        blur_px=blur,
        opacity=round(1.0 - reach * 0.25, 3),
        remark=_remark_for(blur, seed),
    )
