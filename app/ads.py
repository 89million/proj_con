"""THE MONK — fake ad interstitials.

Pure data + eligibility logic, no DB access here (see app/crud.py for the
DB-backed orchestration). One brand, sixteen unrelated products, ordered per
member; #15 (the bar itself) is the permanent last ad, #16 (a bookmark) slots
into the normal rotation ahead of it. See monk-ads-plan.md for the full design
rationale.
"""

from dataclasses import dataclass, field
from datetime import timedelta

# ---------------------------------------------------------------------------
# Eligibility constants
# ---------------------------------------------------------------------------

NEAR_DEADLINE_BUFFER = timedelta(hours=1)

# Just long enough that the redirect landing right after a dismiss doesn't
# itself immediately qualify for the next ad — without this, dismissing ad
# N redirects to a page that instantly shows ad N+1, chaining through all 16
# in one go instead of "one per real visit." The comparison happens entirely
# in the database (see crud.recent_ad_impression_exists) — comparing a
# stored timestamp against Python's own clock is a footgun the moment the
# two disagree on timezone.
MIN_GAP_SECONDS = 45


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


def _band(y: int) -> str:
    """The dark label strip reading THE MONK, crossing an object at height y."""
    return (
        f'<rect x="20" y="{y}" width="200" height="26" fill="#141414"/>'
        f'<text x="120" y="{y + 18}" text-anchor="middle" font-family="Georgia, serif" '
        f'font-weight="700" font-size="14" letter-spacing="2" fill="#f5f0e6">THE MONK</text>'
    )


STARBURST_SVG = (
    '<svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">'
    '<polygon points="50,0 61,38 100,38 68,61 79,100 50,76 21,100 32,61 0,38 39,38" fill="currentColor"/>'
    "</svg>"
)

_SVG_OPEN = '<svg viewBox="0 0 240 210" xmlns="http://www.w3.org/2000/svg">'
_SVG_CLOSE = "</svg>"

SVG_COFFEE = (
    _SVG_OPEN
    + '<ellipse cx="120" cy="52" rx="38" ry="7" fill="currentColor" opacity="0.6"/>'
    + '<rect x="82" y="50" width="76" height="22" rx="4" fill="currentColor"/>'
    + '<rect x="70" y="70" width="100" height="118" rx="10" fill="none" stroke="currentColor" stroke-width="6"/>'
    + _band(118)
    + _SVG_CLOSE
)

SVG_HAIR_TONIC = (
    _SVG_OPEN
    + '<rect x="90" y="66" width="32" height="10" fill="currentColor"/>'
    + '<rect x="96" y="40" width="20" height="30" fill="currentColor"/>'
    + '<path d="M70 188 L70 110 Q70 90 96 90 L116 90 Q142 90 142 110 L142 188 Z" '
    + 'fill="none" stroke="currentColor" stroke-width="6" stroke-linejoin="round"/>'
    + _band(136)
    + _SVG_CLOSE
)

SVG_LAMP = (
    _SVG_OPEN
    + '<path d="M56 78 Q106 22 158 78 L146 96 Q106 58 68 96 Z" fill="currentColor"/>'
    + '<rect x="103" y="94" width="6" height="78" fill="currentColor"/>'
    + '<ellipse cx="106" cy="180" rx="42" ry="8" fill="none" stroke="currentColor" stroke-width="6"/>'
    + _band(100)
    + _SVG_CLOSE
)

SVG_COUGH_SYRUP = (
    _SVG_OPEN
    + '<rect x="78" y="46" width="24" height="26" fill="currentColor"/>'
    + '<rect x="58" y="70" width="64" height="102" rx="8" fill="none" stroke="currentColor" stroke-width="6"/>'
    + '<ellipse cx="172" cy="148" rx="28" ry="17" fill="none" stroke="currentColor" stroke-width="6"/>'
    + '<line x1="195" y1="137" x2="222" y2="106" stroke="currentColor" stroke-width="6" stroke-linecap="round"/>'
    + _band(108)
    + _SVG_CLOSE
)

SVG_MATTRESS = (
    _SVG_OPEN
    + '<rect x="38" y="76" width="164" height="74" rx="14" fill="none" stroke="currentColor" stroke-width="6"/>'
    + '<rect x="46" y="84" width="148" height="58" rx="10" fill="none" stroke="currentColor" stroke-width="2" opacity="0.55"/>'
    + "".join(
        f'<circle cx="{cx}" cy="{cy}" r="3" fill="currentColor"/>'
        for cy in (98, 128)
        for cx in (68, 100, 132, 164)
    )
    + _band(104)
    + _SVG_CLOSE
)

SVG_TYPEFACE = (
    _SVG_OPEN
    + '<text x="120" y="150" text-anchor="middle" font-family="Georgia, serif" '
    + 'font-size="120" font-weight="700" fill="currentColor">Aa</text>'
    + _band(168)
    + _SVG_CLOSE
)

SVG_INSURANCE = (
    _SVG_OPEN
    + '<rect x="55" y="36" width="130" height="150" fill="none" stroke="currentColor" stroke-width="6"/>'
    + '<circle cx="168" cy="168" r="22" fill="none" stroke="currentColor" stroke-width="5"/>'
    + '<line x1="75" y1="66" x2="165" y2="66" stroke="currentColor" stroke-width="4"/>'
    + '<line x1="75" y1="84" x2="165" y2="84" stroke="currentColor" stroke-width="4"/>'
    + '<line x1="75" y1="102" x2="140" y2="102" stroke="currentColor" stroke-width="4"/>'
    + _band(126)
    + _SVG_CLOSE
)

SVG_CEREAL = (
    _SVG_OPEN
    + '<polygon points="70,90 100,75 130,85 128,115 95,125 68,115" fill="none" stroke="currentColor" '
    + 'stroke-width="10" stroke-linejoin="round"/>'
    + '<polygon points="140,108 168,98 190,116 182,143 152,148 132,130" fill="none" stroke="currentColor" '
    + 'stroke-width="10" stroke-linejoin="round"/>'
    + '<polygon points="92,140 119,132 137,150 127,175 97,178 79,162" fill="none" stroke="currentColor" '
    + 'stroke-width="10" stroke-linejoin="round"/>'
    + _band(46)
    + _SVG_CLOSE
)

SVG_INSOLE = (
    _SVG_OPEN
    + '<path d="M70 182 Q54 150 65 108 Q72 78 100 63 Q130 53 150 74 Q166 95 160 130 '
    + 'Q155 166 130 186 Q100 202 70 182 Z" fill="none" stroke="currentColor" stroke-width="6" '
    + 'stroke-linejoin="round"/>'
    + '<path d="M84 148 Q110 138 136 149" fill="none" stroke="currentColor" stroke-width="4"/>'
    + '<ellipse cx="120" cy="88" rx="20" ry="14" fill="none" stroke="currentColor" stroke-width="4"/>'
    + _band(112)
    + _SVG_CLOSE
)

SVG_HOLD_MUSIC = (
    _SVG_OPEN
    + '<line x1="60" y1="66" x2="152" y2="118" stroke="currentColor" stroke-width="10" stroke-linecap="round"/>'
    + '<circle cx="58" cy="62" r="16" fill="currentColor"/>'
    + '<circle cx="154" cy="122" r="16" fill="currentColor"/>'
    + '<rect x="90" y="140" width="80" height="16" rx="4" fill="currentColor"/>'
    + '<circle cx="130" cy="172" r="18" fill="none" stroke="currentColor" stroke-width="5"/>'
    + _band(92)
    + _SVG_CLOSE
)

SVG_SILENCE = (
    _SVG_OPEN
    + '<rect x="100" y="118" width="40" height="52" fill="none" stroke="currentColor" stroke-width="6"/>'
    + '<path d="M88 170 L152 170 L167 190 L73 190 Z" fill="currentColor"/>'
    + _band(84)
    + _SVG_CLOSE
)

SVG_PAINT = (
    _SVG_OPEN
    + '<path d="M95 56 Q120 28 145 56" fill="none" stroke="currentColor" stroke-width="5"/>'
    + '<ellipse cx="120" cy="68" rx="46" ry="12" fill="none" stroke="currentColor" stroke-width="6"/>'
    + '<path d="M74 68 L74 158 Q74 170 120 170 Q166 170 166 158 L166 68" '
    + 'fill="none" stroke="currentColor" stroke-width="6"/>'
    + _band(104)
    + _SVG_CLOSE
)

SVG_WEATHER = (
    _SVG_OPEN
    + '<path d="M60 130 Q50 100 80 95 Q90 70 120 75 Q145 60 165 85 Q195 85 190 115 '
    + 'Q198 140 165 140 L80 140 Q54 140 60 130 Z" fill="currentColor"/>'
    + '<line x1="90" y1="155" x2="85" y2="176" stroke="currentColor" stroke-width="5" stroke-linecap="round"/>'
    + '<line x1="120" y1="155" x2="115" y2="181" stroke="currentColor" stroke-width="5" stroke-linecap="round"/>'
    + '<line x1="150" y1="155" x2="145" y2="176" stroke="currentColor" stroke-width="5" stroke-linecap="round"/>'
    + _band(98)
    + _SVG_CLOSE
)

SVG_BOOKMARK = (
    _SVG_OPEN
    + '<path d="M90 26 L150 26 L150 180 L120 153 L90 180 Z" fill="none" stroke="currentColor" '
    + 'stroke-width="6" stroke-linejoin="round"/>'
    + _band(88)
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
        body="One scoop and the morning starts over. Now in the jar that remembers how much you took.",
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
        body="Applied nightly, it asks nothing of you. Your barber will notice. Your barber will not comment.",
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
        body="Legible at every size except the one you need. Used by three governments and one book club.",
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
        body="No hearts, no moons, no clovers. Just the wood. You have been eating around it your whole life.",
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
        body="Walk further into the book than ever before. Recommended by nobody. Worn by everyone.",
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
        body="Available Tuesdays. Mostly overcast, with intent. Now serving Capitol Hill and the surrounding feeling.",
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
