"""THE MONK — fake ad interstitials.

Pure data + eligibility logic, no DB access here (see app/crud.py for the
DB-backed orchestration). One brand, sixteen unrelated products, ordered per
member; #15 (the bar itself) is the permanent last ad, #16 (a bookmark) slots
into the normal rotation ahead of it. See monk-ads-plan.md for the full design
rationale.
"""

import math
from dataclasses import dataclass, field
from datetime import timedelta

# ---------------------------------------------------------------------------
# Eligibility constants
# ---------------------------------------------------------------------------

NEAR_DEADLINE_BUFFER = timedelta(hours=1)

# The floor between two ads. Its original job was narrow: the redirect landing
# right after a dismiss must not itself immediately qualify, or dismissing ad N
# lands on a page that instantly shows ad N+1 and the member gets marched
# through all 16 in one go. That redirect completes in about a second, so
# anything above a few seconds does the job; the rest of the value is purely
# how often a member who is moving around the site gets interrupted.
#
# Note this is a floor, not a schedule — an ad is only ever rendered on a page
# load, so nothing appears while someone sits still on one page.
#
# The comparison happens entirely in the database (see
# crud.recent_ad_impression_exists) — comparing a stored timestamp against
# Python's own clock is a footgun the moment the two disagree on timezone.
MIN_GAP_SECONDS = 15


# ---------------------------------------------------------------------------
# Ad data
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Ad:
    slug: str
    number: int  # original numbering from the plan (1-16)
    product: str  # short name, shown as the headline
    body: str  # the ad copy paragraph
    closer: str  # italic mock-safety-warning line
    era: str  # print | seventies | pharma | corporate | void
    caption: str | None = None  # small-caps "not shown" line under the object
    svg: str | None = None  # inline SVG object, None for the quiet/void ads
    starburst: bool = False
    quiet: bool = False  # ad #4: no starburst, no misregistration, no object
    filler: list[str] = field(default_factory=list)  # extra disclaimer sub-clauses


# "THE MONK" set in Georgia bold at font-size 14 with letter-spacing 2, measured
# in viewBox units. Everything in _band scales off this.
_WORDMARK_W = 101.0
_BAND_FONT = 14.0
_BAND_PAD = 8.0  # breathing room between the wordmark and the ends of the strip


def _band(y: int, x0: int, x1: int) -> str:
    """The dark label strip reading THE MONK, wrapped across an object.

    `x0`/`x1` are the horizontal extent of the object being labelled, so the
    strip is sized to the thing it is stuck to rather than to the frame. It used
    to be a fixed 200-wide bar in a 240-wide frame, which meant it overhung every
    object narrower than that — 70 units of overhang each side on the bookmark —
    and read as a bar floating near the product rather than a label on it.

    The wordmark shrinks to fit narrow objects instead of forcing the strip wider,
    down to a floor below which it would stop being readable; only objects
    narrower than that floor still get any overhang, and then only a little. The
    strip's height and letter-spacing scale with the type so the proportions hold.
    """
    width = float(x1 - x0)
    cx = (x0 + x1) / 2
    # Largest type that fits this object, capped at the normal size and floored
    # where legibility gives out.
    font = max(9.0, min(_BAND_FONT, _BAND_FONT * (width - 2 * _BAND_PAD) / _WORDMARK_W))
    text_w = _WORDMARK_W * font / _BAND_FONT
    band_w = max(width, text_w + 2 * _BAND_PAD)
    height = font * 26 / _BAND_FONT
    x = cx - band_w / 2
    return (
        f'<rect x="{x:.1f}" y="{y}" width="{band_w:.1f}" height="{height:.1f}" fill="#141414"/>'
        f'<text x="{cx:.1f}" y="{y + height * 0.69:.1f}" text-anchor="middle" '
        f'font-family="Georgia, serif" font-weight="700" font-size="{font:.1f}" '
        f'letter-spacing="{2 * font / _BAND_FONT:.1f}" fill="#f5f0e6">THE MONK</text>'
    )


STARBURST_SVG = (
    '<svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">'
    '<polygon points="50,0 61,38 100,38 68,61 79,100 50,76 21,100 32,61 0,38 39,38" '
    'fill="currentColor"/>'
    "</svg>"
)

_SVG_OPEN = '<svg viewBox="0 0 240 210" xmlns="http://www.w3.org/2000/svg">'
_SVG_CLOSE = "</svg>"

SVG_COFFEE = (
    _SVG_OPEN
    + '<ellipse cx="120" cy="52" rx="38" ry="7" fill="currentColor" opacity="0.6"/>'
    + '<rect x="82" y="50" width="76" height="22" rx="4" fill="currentColor"/>'
    + '<rect x="70" y="70" width="100" height="118" rx="10" fill="none" stroke="currentColor" '
    + 'stroke-width="6"/>'
    + _band(118, 70, 170)
    + _SVG_CLOSE
)

SVG_HAIR_TONIC = (
    _SVG_OPEN
    + '<rect x="90" y="66" width="32" height="10" fill="currentColor"/>'
    + '<rect x="96" y="40" width="20" height="30" fill="currentColor"/>'
    + '<path d="M70 188 L70 110 Q70 90 96 90 L116 90 Q142 90 142 110 L142 188 Z" '
    + 'fill="none" stroke="currentColor" stroke-width="6" stroke-linejoin="round"/>'
    + _band(136, 70, 142)
    + _SVG_CLOSE
)

SVG_LAMP = (
    _SVG_OPEN
    + '<path d="M56 78 Q106 22 158 78 L146 96 Q106 58 68 96 Z" fill="currentColor"/>'
    + '<rect x="103" y="94" width="6" height="78" fill="currentColor"/>'
    + '<ellipse cx="106" cy="180" rx="42" ry="8" fill="none" stroke="currentColor" '
    + 'stroke-width="6"/>'
    + _band(100, 56, 158)
    + _SVG_CLOSE
)

SVG_COUGH_SYRUP = (
    _SVG_OPEN
    + '<rect x="78" y="46" width="24" height="26" fill="currentColor"/>'
    + '<rect x="58" y="70" width="64" height="102" rx="8" fill="none" stroke="currentColor" '
    + 'stroke-width="6"/>'
    + '<ellipse cx="172" cy="148" rx="28" ry="17" fill="none" stroke="currentColor" '
    + 'stroke-width="6"/>'
    + '<line x1="195" y1="137" x2="222" y2="106" stroke="currentColor" stroke-width="6" '
    + 'stroke-linecap="round"/>'
    + _band(108, 58, 222)
    + _SVG_CLOSE
)

SVG_MATTRESS = (
    _SVG_OPEN
    + '<rect x="38" y="76" width="164" height="74" rx="14" fill="none" stroke="currentColor" '
    + 'stroke-width="6"/>'
    + '<rect x="46" y="84" width="148" height="58" rx="10" fill="none" stroke="currentColor" '
    + 'stroke-width="2" opacity="0.55"/>'
    + "".join(
        f'<circle cx="{cx}" cy="{cy}" r="3" fill="currentColor"/>'
        for cy in (98, 128)
        for cx in (68, 100, 132, 164)
    )
    + _band(104, 38, 202)
    + _SVG_CLOSE
)

SVG_TYPEFACE = (
    _SVG_OPEN
    + '<text x="120" y="150" text-anchor="middle" font-family="Georgia, serif" '
    + 'font-size="120" font-weight="700" fill="currentColor">Aa</text>'
    + _band(168, 35, 201)
    + _SVG_CLOSE
)

SVG_INSURANCE = (
    _SVG_OPEN
    + '<rect x="55" y="36" width="130" height="150" fill="none" stroke="currentColor" '
    + 'stroke-width="6"/>'
    + '<circle cx="168" cy="168" r="22" fill="none" stroke="currentColor" stroke-width="5"/>'
    + '<line x1="75" y1="66" x2="165" y2="66" stroke="currentColor" stroke-width="4"/>'
    + '<line x1="75" y1="84" x2="165" y2="84" stroke="currentColor" stroke-width="4"/>'
    + '<line x1="75" y1="102" x2="140" y2="102" stroke="currentColor" stroke-width="4"/>'
    + _band(126, 55, 190)
    + _SVG_CLOSE
)


def _wood() -> str:
    """ "The wood" — the oat half of a bowl of Lucky Charms, drawn honestly.

    Alone among the objects this one keeps its real colours rather than taking
    `currentColor` from the era, because ad #9 is the one whose caption admits
    nothing: the picture has to actually look like toasted oat.

    A piece is an unfilled polygon with a stroke about as wide as its radius —
    that reads as a chunky ring with a small hole, the way an oat piece looks.
    No masks, no compound paths. Twenty-two of them at mixed sizes and rotations
    scatter like a spill; forty speckles keep it from reading as flat plastic.

    Generated rather than written out because it is 22 polygons and 40 circles.
    The seeded generator below is the one from the design mockup, constants and
    call order intact, so the scatter is byte-identical to the drawing that was
    signed off — and identical on every render, which a random one would not be.
    """
    state = 11

    def rnd() -> float:
        nonlocal state
        state = (state * 9301 + 49297) % 233280
        return state / 233280

    def ngon(sides: int, radius: float, rotation: float) -> str:
        pts = []
        for i in range(sides):
            a = rotation + (i * 2 * math.pi) / sides - math.pi / 2
            pts.append(f"{math.cos(a) * radius:.1f},{math.sin(a) * radius:.1f}")
        return " ".join(pts)

    tints = ["#d7c49a", "#cdb98d", "#e0d1ab", "#c6b083"]
    sides = [3, 4, 5, 6]
    parts = []
    for _ in range(22):
        r = 11 + rnd() * 6
        n = sides[int(rnd() * len(sides))]
        cx = 20 + rnd() * 110
        cy = 20 + rnd() * 110
        tint = tints[int(rnd() * len(tints))]
        parts.append(
            f'<polygon points="{ngon(n, r, rnd() * 6.28)}" fill="none" stroke="{tint}"'
            f' stroke-width="{r * 1.05:.1f}" stroke-linejoin="round"'
            f' transform="translate({cx:.1f} {cy:.1f})"/>'
        )
    for _ in range(40):
        parts.append(
            f'<circle cx="{rnd() * 150:.1f}" cy="{rnd() * 150:.1f}"'
            f' r="{0.5 + rnd():.1f}" fill="#9c8a5f" opacity=".35"/>'
        )
    # The scatter is drawn in a 150x150 space; centre it in the shared 240x210 frame.
    return '<g transform="translate(45 30)">' + "".join(parts) + "</g>"


SVG_CEREAL = _SVG_OPEN + _wood() + _band(46, 50, 192) + _SVG_CLOSE

# The first version of this read as a face: a 101x150 near-circular outline with
# an ellipse near the top and an upward curve below it, which the eye assembles
# into eye-and-mouth before it ever considers footwear. The fix is proportion and
# asymmetry rather than more detail — a sole is roughly twice as long as it is
# wide, and its medial edge cuts *inward* at the arch. Nothing symmetrical and
# round enough to be a head survives that.
SVG_INSOLE = (
    _SVG_OPEN
    # Outline, toe at the top: broad forefoot, waist pinched in at the arch on
    # the left, rounded heel at the bottom.
    + '<path d="M120 34 Q152 34 156 74 Q160 104 149 130 Q142 150 141 170 '
    + "Q139 194 118 196 Q96 196 94 172 Q93 152 100 136 Q112 114 100 92 "
    + 'Q90 68 96 54 Q102 34 120 34 Z" fill="none" stroke="currentColor" '
    + 'stroke-width="6" stroke-linejoin="round"/>'
    # Arch support, hugging the concave edge — reads as structure, not a smile,
    # because it runs vertically and sits off-centre.
    + '<path d="M108 92 Q118 114 107 136" fill="none" stroke="currentColor" '
    + 'stroke-width="4" stroke-linecap="round"/>'
    # Heel cup, low and inside the heel where it belongs.
    + '<path d="M103 178 Q118 170 133 179" fill="none" stroke="currentColor" '
    + 'stroke-width="4" stroke-linecap="round"/>'
    + _band(148, 94, 158)
    + _SVG_CLOSE
)

SVG_HOLD_MUSIC = (
    _SVG_OPEN
    + '<line x1="60" y1="66" x2="152" y2="118" stroke="currentColor" stroke-width="10" '
    + 'stroke-linecap="round"/>'
    + '<circle cx="58" cy="62" r="16" fill="currentColor"/>'
    + '<circle cx="154" cy="122" r="16" fill="currentColor"/>'
    + '<rect x="90" y="140" width="80" height="16" rx="4" fill="currentColor"/>'
    + '<circle cx="130" cy="172" r="18" fill="none" stroke="currentColor" stroke-width="5"/>'
    + _band(92, 42, 170)
    + _SVG_CLOSE
)

SVG_SILENCE = (
    _SVG_OPEN
    + '<rect x="100" y="118" width="40" height="52" fill="none" stroke="currentColor" '
    + 'stroke-width="6"/>'
    + '<path d="M88 170 L152 170 L167 190 L73 190 Z" fill="currentColor"/>'
    + _band(84, 73, 167)
    + _SVG_CLOSE
)

SVG_PAINT = (
    _SVG_OPEN
    + '<path d="M95 56 Q120 28 145 56" fill="none" stroke="currentColor" stroke-width="5"/>'
    + '<ellipse cx="120" cy="68" rx="46" ry="12" fill="none" stroke="currentColor" '
    + 'stroke-width="6"/>'
    + '<path d="M74 68 L74 158 Q74 170 120 170 Q166 170 166 158 L166 68" '
    + 'fill="none" stroke="currentColor" stroke-width="6"/>'
    + _band(104, 74, 166)
    + _SVG_CLOSE
)

SVG_WEATHER = (
    _SVG_OPEN
    + '<path d="M60 130 Q50 100 80 95 Q90 70 120 75 Q145 60 165 85 Q195 85 190 115 '
    + 'Q198 140 165 140 L80 140 Q54 140 60 130 Z" fill="currentColor"/>'
    + '<line x1="90" y1="155" x2="85" y2="176" stroke="currentColor" stroke-width="5" '
    + 'stroke-linecap="round"/>'
    + '<line x1="120" y1="155" x2="115" y2="181" stroke="currentColor" stroke-width="5" '
    + 'stroke-linecap="round"/>'
    + '<line x1="150" y1="155" x2="145" y2="176" stroke="currentColor" stroke-width="5" '
    + 'stroke-linecap="round"/>'
    + _band(98, 58, 192)
    + _SVG_CLOSE
)

SVG_BOOKMARK = (
    _SVG_OPEN
    + '<path d="M90 26 L150 26 L150 180 L120 153 L90 180 Z" fill="none" stroke="currentColor" '
    + 'stroke-width="6" stroke-linejoin="round"/>'
    + _band(88, 90, 150)
    + _SVG_CLOSE
)


_FILLER_CLAUSES = [
    "Consult your book club before use.",
    "Terms subject to change without notice, and have.",
    "Void where prohibited, prohibited where void.",
    "See club bylaws for full conditions (none exist).",
    "Individual chapters may vary.",
    "Not valid in all reading formats.",
]


def _filler(era: str, index: int) -> list[str]:
    if era == "pharma":
        return [_FILLER_CLAUSES[index % len(_FILLER_CLAUSES)]]
    if era == "corporate":
        return [
            _FILLER_CLAUSES[index % len(_FILLER_CLAUSES)],
            _FILLER_CLAUSES[(index + 1) % len(_FILLER_CLAUSES)],
        ]
    return []


# Rotation order: 1-14, then 16, then 15 (the bar stays the permanent ending).
ADS: list[Ad] = [
    Ad(
        slug="coffee",
        number=1,
        product="Instant coffee",
        body="One scoop and the morning starts over. Now in the jar that remembers how much you "
        "took.",
        closer="Safe when taken as directed.",
        era="print",
        caption="Steam not shown. Warmth not shown. Not shown: product.",
        svg=SVG_COFFEE,
        starburst=True,
    ),
    Ad(
        slug="hair-tonic",
        number=2,
        product="Hair tonic",
        body="Applied nightly, it asks nothing of you. Your barber will notice. Your barber will "
        "not comment.",
        closer="Do not apply to the scalp of another.",
        era="print",
        caption="Scent not shown. Consent not shown. Not shown: product.",
        svg=SVG_HAIR_TONIC,
        starburst=True,
    ),
    Ad(
        slug="lamp",
        number=3,
        product="The reading lamp",
        body="Knows which page you stopped on. Never brighter than the room requires.",
        closer="Not a lamp in the conventional sense.",
        era="print",
        caption="Light not shown. Page not shown. Not shown: product.",
        svg=SVG_LAMP,
        starburst=True,
    ),
    Ad(
        slug="bar",
        number=4,
        product="Capitol Hill",
        body="The one you already know. Same booth, same lighting. Friday, probably.",
        closer="Please drink responsibly.",
        era="print",
        quiet=True,
    ),
    Ad(
        slug="cough-syrup",
        number=5,
        product="Cough syrup",
        body="Two spoonfuls and the sentence finishes itself. Cherry, or the memory of cherry.",
        closer="Do not operate a bracket while drowsy.",
        era="seventies",
        caption="Cherry not shown. Sentence not shown. Not shown: product.",
        svg=SVG_COUGH_SYRUP,
    ),
    Ad(
        slug="mattress",
        number=6,
        product="The mattress",
        body="Gives up before you do. Eight hours guaranteed, whether or not you are in it.",
        closer="Individual results have been discontinued.",
        era="seventies",
        caption="Shown smaller than actual size.",
        svg=SVG_MATTRESS,
    ),
    Ad(
        slug="typeface",
        number=7,
        product="A typeface",
        body="Legible at every size except the one you need. Used by three governments and one "
        "book "
        "club.",
        closer="Kerning is final and cannot be appealed.",
        era="seventies",
        caption="Kerning not shown. Legibility not shown. Not shown: product.",
        svg=SVG_TYPEFACE,
    ),
    Ad(
        slug="insurance",
        number=8,
        product="Insurance against the ending",
        body="Full coverage from page one. Claims processed in the order they were dreaded.",
        closer="Does not cover the middle.",
        era="pharma",
        caption="Coverage not shown. Middle not shown. Not shown: product.",
        svg=SVG_INSURANCE,
        filler=_filler("pharma", 8),
    ),
    Ad(
        slug="cereal",
        number=9,
        product="Breakfast cereal",
        body="No hearts, no moons, no clovers. Just the wood. You have been eating around it your "
        "whole life.",
        closer="No part of this product was ever fun.",
        era="pharma",
        caption="Actual product shown.",
        svg=SVG_CEREAL,
        filler=_filler("pharma", 9),
    ),
    Ad(
        slug="insoles",
        number=10,
        product="Shoe insoles",
        body="Walk further into the book than ever before. Recommended by nobody. Worn by "
        "everyone.",
        closer="Do not remove while standing.",
        era="pharma",
        caption="Distance not shown. Nobody's recommendation shown. Not shown: product.",
        svg=SVG_INSOLE,
        filler=_filler("pharma", 10),
    ),
    Ad(
        slug="hold-music",
        number=11,
        product="Hold music",
        body="Four minutes, then four minutes again. You will be told your call is important.",
        closer="Position in queue is not a number.",
        era="pharma",
        caption="Queue position not shown. Importance not shown. Not shown: product.",
        svg=SVG_HOLD_MUSIC,
        filler=_filler("pharma", 11),
    ),
    Ad(
        slug="silence",
        number=12,
        product="A silence",
        body="Sold by the hour, delivered in the evening. Fits any room. Fits this room.",
        closer="Cannot be returned once opened.",
        era="corporate",
        caption="Room not shown. Hour not shown. Not shown: product.",
        svg=SVG_SILENCE,
        filler=_filler("corporate", 12),
    ),
    Ad(
        slug="paint",
        number=13,
        product="Interior paint",
        body="The colour of a page you have not turned. Two coats. Dries the moment you look away.",
        closer="Colour may differ from colour.",
        era="corporate",
        caption="Colour not shown. Other colour not shown. Not shown: product.",
        svg=SVG_PAINT,
        filler=_filler("corporate", 13),
    ),
    Ad(
        slug="weather",
        number=14,
        product="Weather",
        body="Available Tuesdays. Mostly overcast, with intent. Now serving Capitol Hill and the "
        "surrounding feeling.",
        closer="Forecast is binding.",
        era="corporate",
        caption="Typeface not shown. Colour not shown. Weather shown. Not shown: product.",
        svg=SVG_WEATHER,
        filler=_filler("corporate", 14),
    ),
    Ad(
        slug="bookmark",
        number=16,
        product="A bookmark",
        body="Holds your place whether or not you come back. Slim enough to lose.",
        closer="Not responsible for the pages on either side.",
        era="corporate",
        caption="Page not shown. Return not shown. Not shown: product.",
        svg=SVG_BOOKMARK,
        filler=_filler("corporate", 16),
    ),
    Ad(
        slug="booth",
        number=15,
        product="THE MONK",
        body=(
            "I was here before the club. I will be here after the book. I am the booth. "
            "I am the last round. I am closing time."
        ),
        closer="Available wherever you have already agreed to meet.",
        era="void",
        quiet=True,
    ),
]

BY_SLUG: dict[str, Ad] = {ad.slug: ad for ad in ADS}


def next_ad_for(seen_slugs: set[str]) -> Ad | None:
    """Lowest-ordered ad this member hasn't been shown yet, or None once they've seen all 16."""
    for ad in ADS:
        if ad.slug not in seen_slugs:
            return ad
    return None


def is_eligible(
    *,
    ads_enabled: bool,
    user_opted_out: bool,
    unseen_ad: Ad | None,
    near_deadline: bool,
    recent_impression: bool,
) -> bool:
    """Whether to show `unseen_ad` right now. Pure — no I/O, easy to reason about at each call site.

    This is a guided walk through all 16, not a slow drip: no weekly cap, no
    long cooldown — just MIN_GAP_SECONDS (`recent_impression`), which exists
    solely so the redirect right after a dismiss doesn't immediately qualify
    for the next one. It ends itself — see crud.record_ad_impression, which
    opts the member out once the last ad in the rotation has been shown.
    """
    if not ads_enabled or user_opted_out:
        return False
    if unseen_ad is None:
        return False
    if near_deadline:
        return False
    if recent_impression:
        return False
    return True
