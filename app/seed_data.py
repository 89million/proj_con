"""Curated sample books and helpers for the dev simulation tools.

Used by both the in-app god-mode buttons (auto-submit) and the seed script.
Titles/authors are real so OpenLibrary cover lookups resolve to actual covers.
"""

import random

# (title, author, page_count)
SAMPLE_BOOKS: list[tuple[str, str, int]] = [
    ("The Name of the Wind", "Patrick Rothfuss", 662),
    ("Project Hail Mary", "Andy Weir", 476),
    ("The Left Hand of Darkness", "Ursula K. Le Guin", 304),
    ("Piranesi", "Susanna Clarke", 245),
    ("Klara and the Sun", "Kazuo Ishiguro", 303),
    ("The Fifth Season", "N. K. Jemisin", 468),
    ("Station Eleven", "Emily St. John Mandel", 333),
    ("A Gentleman in Moscow", "Amor Towles", 462),
    ("The Goldfinch", "Donna Tartt", 771),
    ("Circe", "Madeline Miller", 393),
    ("Educated", "Tara Westover", 334),
    ("The Overstory", "Richard Powers", 502),
    ("Pachinko", "Min Jin Lee", 490),
    ("The Night Circus", "Erin Morgenstern", 387),
    ("Never Let Me Go", "Kazuo Ishiguro", 288),
    ("The Road", "Cormac McCarthy", 287),
    ("Cloud Atlas", "David Mitchell", 509),
    ("The Three-Body Problem", "Liu Cixin", 400),
    ("Normal People", "Sally Rooney", 273),
    ("A Little Life", "Hanya Yanagihara", 720),
]


def pick_books(
    count: int,
    *,
    exclude_titles: set[str] | None = None,
    max_pages: int | None = None,
) -> list[tuple[str, str, int]]:
    """Return up to `count` distinct sample books, skipping excluded titles and
    any book longer than `max_pages` (when given)."""
    exclude = exclude_titles or set()
    pool = [
        b for b in SAMPLE_BOOKS if b[0] not in exclude and (max_pages is None or b[2] <= max_pages)
    ]
    random.shuffle(pool)
    return pool[:count]
