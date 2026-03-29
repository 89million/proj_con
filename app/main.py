"""FastAPI application — all routes."""

import html as _html
import math
from datetime import datetime, timedelta

import httpx
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import BaseHTTPMiddleware

from app import crud, notify, state, voting
from app.auth import (
    build_authorization_url,
    create_session_token,
    exchange_code_for_user_info,
    get_current_user,
    get_or_create_user,
)
from app.config import settings
from app.database import get_db
from app.models import IdeaStatus, ReadBook, SeasonState, User


class NoCacheMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        if not request.url.path.startswith("/static"):
            response.headers["Cache-Control"] = "no-store"
        return response


app = FastAPI(title="Stumbling Book Club")
app.add_middleware(NoCacheMiddleware)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")
templates.env.filters["unescape"] = _html.unescape


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

_ROUND_LABELS = ["Final", "Semifinals", "Quarterfinals", "Round of 16", "Round of 32"]


def _total_rounds_for_books(n_books: int) -> int:
    """Number of bracket rounds needed for n_books."""
    if n_books < 2:
        return 1
    return math.ceil(math.log2(n_books))


async def is_login_allowed(db: AsyncSession, email: str) -> bool:
    """Return True if this email is permitted to log in.

    Priority order:
    1. ALLOWED_EMAILS env var includes this email → always allow (env var override / bootstrap).
    2. Email exists in the users table (admin pre-registered them) → allow.
    3. The users table is completely empty → allow (first-admin bootstrap).
    4. Otherwise → deny.

    This means the DB is the day-to-day source of truth: an admin adding a
    member via the admin panel is sufficient to grant them login access.
    ALLOWED_EMAILS only needs to contain the first admin's email for the
    initial bootstrap.
    """
    if settings.is_email_allowed(email):
        return True
    user_count = (await db.execute(select(func.count()).select_from(User))).scalar_one()
    if user_count == 0:
        return True  # empty DB — let first admin in to bootstrap
    email_in_db = (
        await db.execute(select(User.id).where(func.lower(User.email) == email.strip().lower()))
    ).scalar_one_or_none()
    return email_in_db is not None


def build_round_names(max_round: int) -> dict[int, str]:
    """Map round numbers to display names based on total rounds in the bracket."""
    return {max_round - i: label for i, label in enumerate(_ROUND_LABELS) if max_round - i >= 1}


def matchup_tiebreaker(
    matchup: "BracketMatchup",  # noqa: F821
    prior_nominations: dict[int, int],
) -> str | None:
    """Return which tiebreaker decided a resolved matchup, or None if votes were decisive.

    Returns:
        None          — votes were not tied (or no votes cast)
        "veteran"     — tie broken by prior nomination count
        "first_vote"  — tie broken by earliest first-vote timestamp
    """
    if not matchup.votes or matchup.winner_id is None:
        return None
    votes_a = sum(1 for v in matchup.votes if v.book_id == matchup.book_a_id)
    votes_b = sum(1 for v in matchup.votes if v.book_id == matchup.book_b_id)
    if votes_a != votes_b:
        return None
    a_noms = prior_nominations.get(matchup.book_a_id, 0)
    b_noms = prior_nominations.get(matchup.book_b_id, 0)
    if a_noms != b_noms:
        return "veteran"
    return "first_vote"


def seed_tiebreakers(
    seeds: list,  # list[Seed]
    borda_scores: dict[int, int],
    prior_nominations: dict[int, int],
) -> dict[int, str | None]:
    """For each book_id in seeds, return which tiebreaker determined its seed position.

    Returns:
        {book_id: None}               — Borda score was unique (no tiebreaker needed)
        {book_id: "veteran"}          — tie broken by prior nomination count
        {book_id: "submission_order"} — tie broken by submission timestamp
    """
    from collections import defaultdict

    score_groups: dict[int, list] = defaultdict(list)
    for s in seeds:
        score_groups[borda_scores.get(s.book_id, 0)].append(s)

    result: dict[int, str | None] = {}
    for group in score_groups.values():
        if len(group) == 1:
            result[group[0].book_id] = None
            continue
        noms = {s.book_id: prior_nominations.get(s.book_id, 0) for s in group}
        reason = "veteran" if len(set(noms.values())) > 1 else "submission_order"
        # Only the book that WON the tiebreak (lowest seed number) gets the badge.
        winner_seed = min(group, key=lambda s: s.seed)
        for s in group:
            result[s.book_id] = reason if s.book_id == winner_seed.book_id else None
    return result


# ---------------------------------------------------------------------------
# Dependency helpers
# ---------------------------------------------------------------------------


async def get_user_or_none(request: Request, db: AsyncSession = Depends(get_db)) -> User | None:
    return await get_current_user(request, db)


async def require_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    user = await get_current_user(request, db)
    if user is None:
        raise HTTPException(status_code=302, headers={"Location": "/auth/login"})
    return user


async def require_admin(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    user = await get_current_user(request, db)
    if user is None:
        raise HTTPException(status_code=302, headers={"Location": "/auth/login"})
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required.")
    return user


# ---------------------------------------------------------------------------
# Root
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def root(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_user_or_none),
):
    if user is None:
        return templates.TemplateResponse("landing.html", {"request": request})

    season = await crud.get_active_season(db)
    if season is not None:
        if season.state == SeasonState.submit:
            return RedirectResponse("/submit", status_code=302)
        elif season.state == SeasonState.ranking:
            return RedirectResponse("/ranking", status_code=302)
        elif season.state == SeasonState.bracket:
            return RedirectResponse("/bracket", status_code=302)
        elif season.state == SeasonState.complete:
            return RedirectResponse("/complete", status_code=302)

    # Truly no history — show the "no season" page (admin sees start button)
    return templates.TemplateResponse("no_season.html", {"request": request, "user": user})


@app.get("/how-it-works", response_class=HTMLResponse)
async def how_it_works(
    request: Request,
    user: User | None = Depends(get_user_or_none),
):
    return templates.TemplateResponse("how_it_works.html", {"request": request, "user": user})


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


@app.get("/auth/login")
async def auth_login():
    url = build_authorization_url()
    return RedirectResponse(url)


@app.get("/auth/callback")
async def auth_callback(
    request: Request,
    code: str,
    db: AsyncSession = Depends(get_db),
):
    try:
        user_info = await exchange_code_for_user_info(code)
    except Exception:
        raise HTTPException(status_code=400, detail="OAuth failed. Please try again.")

    email = user_info.get("email", "")
    if not await is_login_allowed(db, email):
        return RedirectResponse("/?error=not_invited", status_code=302)

    user = await get_or_create_user(db, user_info)
    token = create_session_token(user.id)

    response = RedirectResponse("/", status_code=302)
    response.set_cookie(
        "session",
        token,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 30,
    )
    return response


@app.get("/auth/logout")
async def auth_logout():
    response = RedirectResponse("/", status_code=302)
    response.delete_cookie("session")
    return response


# ---------------------------------------------------------------------------
# Submit state
# ---------------------------------------------------------------------------


@app.get("/submit", response_class=HTMLResponse)
async def submit_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_user),
):
    season = await crud.get_active_season(db)
    if season is None or season.state != SeasonState.submit:
        return RedirectResponse("/", status_code=302)

    is_spectator = not await crud.is_participant(db, season.id, user.id)
    my_book = await crud.get_book_submitted_by_user(db, user.id, season.id)
    waiting_on = await crud.users_who_havent_submitted(db, season.id)
    all_submissions = await crud.get_books_for_season(db, season.id)
    past_picks = (
        await crud.get_resubmittable_books(db, user.id, season.id)
        if not my_book and not is_spectator
        else []
    )

    return templates.TemplateResponse(
        "submit.html",
        {
            "request": request,
            "user": user,
            "season": season,
            "my_book": my_book,
            "waiting_on": waiting_on,
            "all_submissions": all_submissions,
            "past_picks": past_picks,
            "is_spectator": is_spectator,
        },
    )


@app.post("/submit", response_class=HTMLResponse)
async def submit_book(
    request: Request,
    title: str = Form(...),
    author: str = Form(...),
    page_count: int = Form(...),
    description: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_user),
):
    season = await crud.get_active_season(db)
    if season is None or season.state != SeasonState.submit:
        return RedirectResponse("/", status_code=302)

    if not await crud.is_participant(db, season.id, user.id):
        return RedirectResponse("/submit", status_code=302)

    errors = []

    # Already submitted?
    existing = await crud.get_book_submitted_by_user(db, user.id, season.id)
    if existing:
        errors.append("You've already submitted a book this season.")

    # Page count limit
    if page_count > season.page_limit:
        errors.append(f"Book exceeds the {season.page_limit}-page limit ({page_count} pages).")

    # Description word limit
    if description and len(description.split()) > 120:
        errors.append("Description must be 120 words or fewer.")

    # Blocked?
    if not errors:
        blocked, reason = await crud.is_book_blocked(db, title, author, season.id)
        if blocked:
            errors.append(reason)

    if errors:
        waiting_on = await crud.users_who_havent_submitted(db, season.id)
        all_submissions = await crud.get_books_for_season(db, season.id)
        return templates.TemplateResponse(
            "submit.html",
            {
                "request": request,
                "user": user,
                "season": season,
                "my_book": None,
                "waiting_on": waiting_on,
                "all_submissions": all_submissions,
                "errors": errors,
                "form": {
                    "title": title,
                    "author": author,
                    "page_count": page_count,
                    "description": description,
                },
            },
        )

    await crud.create_book(
        db, title, author, page_count, user.id, season.id, description=description or None
    )
    await state.maybe_advance_from_submit(db, season)

    return RedirectResponse("/submit", status_code=302)


@app.post("/submit/opt-out", response_class=HTMLResponse)
async def opt_out_of_season(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_user),
):
    season = await crud.get_active_season(db)
    if season is None or season.state != SeasonState.submit:
        return RedirectResponse("/", status_code=302)

    # Can't opt out after submitting a book
    existing = await crud.get_book_submitted_by_user(db, user.id, season.id)
    if existing:
        return RedirectResponse("/submit", status_code=302)

    await crud.remove_participant(db, season.id, user.id)
    await state.maybe_advance_from_submit(db, season)
    return RedirectResponse("/", status_code=302)


# ---------------------------------------------------------------------------
# Ranking state
# ---------------------------------------------------------------------------


@app.get("/ranking", response_class=HTMLResponse)
async def ranking_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_user),
):
    season = await crud.get_active_season(db)
    if season is None or season.state != SeasonState.ranking:
        return RedirectResponse("/", status_code=302)

    is_spectator = not await crud.is_participant(db, season.id, user.id)
    books = await crud.get_books_for_season(db, season.id)
    my_votes = await crud.get_borda_votes_for_user(db, user.id, season.id)
    waiting_on = await crud.users_who_havent_ranked(db, season.id)

    # If user already voted, show their ranking
    if my_votes:
        vote_map = {v.book_id: v.rank for v in my_votes}
        ranked_books = sorted(books, key=lambda b: vote_map.get(b.id, 999))
    else:
        ranked_books = books

    return templates.TemplateResponse(
        "ranking.html",
        {
            "request": request,
            "user": user,
            "season": season,
            "books": ranked_books,
            "my_votes": my_votes,
            "waiting_on": waiting_on,
            "is_spectator": is_spectator,
        },
    )


@app.post("/ranking", response_class=HTMLResponse)
async def submit_ranking(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_user),
):
    season = await crud.get_active_season(db)
    if season is None or season.state != SeasonState.ranking:
        return RedirectResponse("/", status_code=302)

    if not await crud.is_participant(db, season.id, user.id):
        return RedirectResponse("/ranking", status_code=302)

    # Already ranked?
    existing = await crud.get_borda_votes_for_user(db, user.id, season.id)
    if existing:
        return RedirectResponse("/ranking", status_code=302)

    form_data = await request.form()
    # Expect fields named "rank_{book_id}" with integer values 1..N
    books = await crud.get_books_for_season(db, season.id)
    try:
        ranked: dict[int, int] = {}  # {book_id: rank}
        for book in books:
            rank_val = form_data.get(f"rank_{book.id}")
            if rank_val is None:
                raise ValueError(f"Missing rank for book {book.id}")
            ranked[book.id] = int(rank_val)
    except (ValueError, TypeError):
        return RedirectResponse("/ranking?error=invalid", status_code=302)

    # Validate all ranks 1..N, no duplicates
    ranks = list(ranked.values())
    n = len(books)
    if sorted(ranks) != list(range(1, n + 1)):
        return RedirectResponse("/ranking?error=invalid", status_code=302)

    # Save as ordered list (rank 1 first)
    ordered_ids = [book_id for book_id, _ in sorted(ranked.items(), key=lambda x: x[1])]
    await crud.save_borda_votes(db, user.id, season.id, ordered_ids)
    await state.maybe_advance_from_ranking(db, season)

    return RedirectResponse("/ranking", status_code=302)


# ---------------------------------------------------------------------------
# Bracket state
# ---------------------------------------------------------------------------


@app.get("/bracket", response_class=HTMLResponse)
async def bracket_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_user),
):
    season = await crud.get_active_season(db)
    if season is None or season.state != SeasonState.bracket:
        return RedirectResponse("/", status_code=302)

    # Self-heal: if all matchups are resolved but season isn't complete,
    # rebuild the missing next round.
    await state.maybe_advance_bracket_round(db, season)

    is_spectator = not await crud.is_participant(db, season.id, user.id)
    current_round = await crud.get_current_bracket_round(db, season.id)
    all_matchups = await crud.get_matchups_for_season(db, season.id)
    seeds = await crud.get_seeds_for_season(db, season.id)
    waiting_on = await crud.users_who_havent_voted_round(db, season.id, current_round)

    # Which matchups has this user voted on?
    user_votes: dict[int, int] = {}  # {matchup_id: book_id}
    if not is_spectator:
        for matchup in all_matchups:
            vote = await crud.get_bracket_vote(db, user.id, matchup.id)
            if vote:
                user_votes[matchup.id] = vote.book_id

    # Count books actually in the bracket (excludes relegated books)
    bracket_book_ids = {m.book_a_id for m in all_matchups} | {m.book_b_id for m in all_matchups}
    n_bracket_books = len(bracket_book_ids) if bracket_book_ids else len(seeds)
    total_rounds = _total_rounds_for_books(n_bracket_books)
    round_names = build_round_names(total_rounds)

    # Build seed lookup: book_id -> seed number
    seed_map = {s.book_id: s.seed for s in seeds}

    prior_nominations = await crud.get_prior_nomination_counts(db, season.id)
    matchup_tiebreakers = {m.id: matchup_tiebreaker(m, prior_nominations) for m in all_matchups}

    return templates.TemplateResponse(
        "bracket.html",
        {
            "request": request,
            "user": user,
            "season": season,
            "matchups": all_matchups,
            "current_round": current_round,
            "seeds": seeds,
            "seed_map": seed_map,
            "user_votes": user_votes,
            "waiting_on": waiting_on,
            "round_names": round_names,
            "total_rounds": total_rounds,
            "prior_nominations": prior_nominations,
            "matchup_tiebreakers": matchup_tiebreakers,
            "is_spectator": is_spectator,
        },
    )


@app.post("/bracket/vote/{matchup_id}", response_class=HTMLResponse)
async def bracket_vote(
    matchup_id: int,
    book_id: int = Form(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_user),
):
    season = await crud.get_active_season(db)
    if season is None or season.state != SeasonState.bracket:
        return RedirectResponse("/", status_code=302)

    if not await crud.is_participant(db, season.id, user.id):
        return RedirectResponse("/bracket", status_code=302)

    matchup = await crud.get_matchup_by_id(db, matchup_id)
    if matchup is None or matchup.season_id != season.id:
        raise HTTPException(status_code=404, detail="Matchup not found.")

    # Only allow voting on current round
    current_round = await crud.get_current_bracket_round(db, season.id)
    if matchup.round != current_round:
        return RedirectResponse("/bracket", status_code=302)

    # Prevent double vote
    existing = await crud.get_bracket_vote(db, user.id, matchup_id)
    if existing:
        return RedirectResponse("/bracket", status_code=302)

    # Validate book_id is in this matchup
    if book_id not in (matchup.book_a_id, matchup.book_b_id):
        raise HTTPException(status_code=400, detail="Invalid book choice.")

    await crud.save_bracket_vote(db, user.id, matchup_id, book_id)
    await state.maybe_advance_bracket_round(db, season)

    return RedirectResponse("/bracket", status_code=302)


@app.post("/bracket/vote-all", response_class=HTMLResponse)
async def bracket_vote_all(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_user),
):
    """Submit all bracket votes for the current round at once."""
    season = await crud.get_active_season(db)
    if season is None or season.state != SeasonState.bracket:
        return RedirectResponse("/", status_code=302)

    current_round = await crud.get_current_bracket_round(db, season.id)
    form_data = await request.form()

    # Collect vote_{matchup_id} = book_id fields
    for key, value in form_data.items():
        if not key.startswith("vote_"):
            continue
        try:
            matchup_id = int(key.removeprefix("vote_"))
            book_id = int(value)
        except (ValueError, TypeError):
            continue

        matchup = await crud.get_matchup_by_id(db, matchup_id)
        if matchup is None or matchup.season_id != season.id:
            continue
        if matchup.round != current_round:
            continue
        existing = await crud.get_bracket_vote(db, user.id, matchup_id)
        if existing:
            continue
        if book_id not in (matchup.book_a_id, matchup.book_b_id):
            continue

        await crud.save_bracket_vote(db, user.id, matchup_id, book_id)

    await state.maybe_advance_bracket_round(db, season)
    return RedirectResponse("/bracket", status_code=302)


# ---------------------------------------------------------------------------
# Complete state
# ---------------------------------------------------------------------------


@app.get("/complete", response_class=HTMLResponse)
async def complete_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_user),
):
    season = await crud.get_most_recent_complete_season(db)
    winner_book = None
    has_meetup = False
    if season:
        winner_book = await crud.get_winner_book_for_season(db, season.id)
        meetup = await crud.get_active_meetup(db)
        has_meetup = meetup is not None

    return templates.TemplateResponse(
        "complete.html",
        {
            "request": request,
            "user": user,
            "season": season,
            "winner_book": winner_book,
            "has_meetup": has_meetup,
        },
    )


@app.get("/history", response_class=HTMLResponse)
async def history_page(
    request: Request,
    tab: str = "seasons",
    submitted: int = 0,
    duplicate: int = 0,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_user),
):
    complete_seasons = await crud.get_complete_seasons(db)
    seasons_with_winners = []
    for s in complete_seasons:
        winner = await crud.get_winner_book_for_season(db, s.id)
        seasons_with_winners.append((s, winner))

    read_books = []
    avg_ratings: dict[int, float] = {}
    review_counts: dict[int, int] = {}
    if tab == "books":
        read_books = await crud.get_approved_read_books(db)
        avg_ratings = await crud.get_average_ratings(db)
        review_counts = await crud.get_review_counts(db)

    return templates.TemplateResponse(
        "history.html",
        {
            "request": request,
            "user": user,
            "seasons_with_winners": seasons_with_winners,
            "read_books": read_books,
            "avg_ratings": avg_ratings,
            "review_counts": review_counts,
            "tab": tab,
            "submitted": submitted,
            "duplicate": duplicate,
        },
    )


@app.post("/history/suggest-book", response_class=HTMLResponse)
async def suggest_read_book(
    title: str = Form(...),
    author: str = Form(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_user),
):
    title = title.strip()
    author = author.strip()
    if title and author:
        if await crud.is_read_book_duplicate(db, title, author):
            return RedirectResponse("/history?tab=books&duplicate=1", status_code=302)
        await crud.submit_read_book(db, title, author, user.id)
    return RedirectResponse("/history?tab=books&submitted=1", status_code=302)


@app.get("/history/{season_id}", response_class=HTMLResponse)
async def history_season_page(
    season_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_user),
):
    season = await crud.get_season_by_id(db, season_id)
    if season is None or season.state != SeasonState.complete:
        raise HTTPException(status_code=404, detail="Season not found.")

    books = await crud.get_books_for_season(db, season_id)
    seeds = await crud.get_seeds_for_season(db, season_id)
    matchups = await crud.get_matchups_for_season(db, season_id)
    winner_book = await crud.get_winner_book_for_season(db, season_id)
    # Count books actually in the bracket (excludes relegated books)
    bracket_book_ids = {m.book_a_id for m in matchups} | {m.book_b_id for m in matchups}
    n_bracket_books = len(bracket_book_ids) if bracket_book_ids else len(books)
    total_rounds = _total_rounds_for_books(n_bracket_books)
    round_names = build_round_names(total_rounds)

    # Borda scores: (N_books - rank) per vote, summed per book
    all_borda_votes = await crud.get_all_borda_votes_for_season(db, season_id)
    borda_scores: dict[int, int] = {}
    for vote in all_borda_votes:
        borda_scores[vote.book_id] = borda_scores.get(vote.book_id, 0) + (len(books) - vote.rank)

    prior_nominations = await crud.get_prior_nomination_counts(db, season_id)
    matchup_ties = {m.id: matchup_tiebreaker(m, prior_nominations) for m in matchups}
    seed_ties = seed_tiebreakers(seeds, borda_scores, prior_nominations)

    # Playoff performance tier for subtle row coloring in the seeds table.
    # Tiers: "winner" | "final" | "semi" | "early" | "relegated"
    book_playoff: dict[int, str] = {}
    if matchups and winner_book:
        max_round = max(m.round for m in matchups)
        for book in books:
            bid = book.id
            if bid == winner_book.id:
                book_playoff[bid] = "winner"
            elif bid not in bracket_book_ids:
                book_playoff[bid] = "relegated"
            else:
                lost_round = 0
                for m in matchups:
                    if m.book_a_id == m.book_b_id:
                        continue
                    if bid in (m.book_a_id, m.book_b_id) and m.winner_id and m.winner_id != bid:
                        lost_round = max(lost_round, m.round)
                if lost_round == max_round:
                    book_playoff[bid] = "final"
                elif lost_round == max_round - 1:
                    book_playoff[bid] = "semi"
                else:
                    book_playoff[bid] = "early"

    return templates.TemplateResponse(
        "history_season.html",
        {
            "request": request,
            "user": user,
            "season": season,
            "books": books,
            "seeds": seeds,
            "matchups": matchups,
            "winner_book": winner_book,
            "round_names": round_names,
            "borda_scores": borda_scores,
            "prior_nominations": prior_nominations,
            "total_rounds": total_rounds,
            "matchup_tiebreakers": matchup_ties,
            "seed_tiebreakers": seed_ties,
            "book_playoff": book_playoff,
        },
    )


@app.get("/history/book/{read_book_id}", response_class=HTMLResponse)
async def book_detail_page(
    read_book_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_user),
):
    rb = await db.get(ReadBook, read_book_id)
    if rb is None or rb.pending:
        raise HTTPException(status_code=404, detail="Book not found.")
    reviews = await crud.get_reviews_for_book(db, read_book_id)
    my_review = next((r for r in reviews if r.user_id == user.id), None)
    avg_rating = round(sum(r.rating for r in reviews) / len(reviews), 1) if reviews else None
    return templates.TemplateResponse(
        "book_detail.html",
        {
            "request": request,
            "user": user,
            "book": rb,
            "reviews": reviews,
            "my_review": my_review,
            "avg_rating": avg_rating,
        },
    )


@app.post("/history/book/{read_book_id}/review", response_class=HTMLResponse)
async def save_book_review(
    read_book_id: int,
    rating: int = Form(...),
    review_text: str = Form(""),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_user),
):
    rb = await db.get(ReadBook, read_book_id)
    if rb is None or rb.pending:
        raise HTTPException(status_code=404, detail="Book not found.")
    if not 1 <= rating <= 5:
        raise HTTPException(status_code=422, detail="Rating must be 1–5.")
    text = review_text.strip()[:2500] or None
    await crud.save_review(db, read_book_id, user.id, rating, text)
    return RedirectResponse(f"/history/book/{read_book_id}", status_code=302)


# ---------------------------------------------------------------------------
# Partials (HTMX polling) and API helpers
# ---------------------------------------------------------------------------


@app.post("/api/suggest-description", response_class=HTMLResponse)
async def suggest_description(
    title: str = Form(...),
    author: str = Form(...),
    _user: User = Depends(require_user),
):
    """Return a pre-filled description textarea via HTMX swap."""
    css = (
        "w-full border border-forest-200 rounded-lg px-3 py-2 text-sm "
        "focus:outline-none focus:ring-2 focus:ring-forest-400 text-forest-900"
    )
    try:
        from google import genai as google_genai

        client = google_genai.Client(api_key=settings.gemini_api_key)
        result = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=(
                f"Write exactly 2 sentences describing the book '{title}' by {author}. "
                "Be concise and informative. Do NOT reveal plot twists, endings, or spoilers. "
                "Focus on premise and themes only. No preamble, no quotes around your answer."
            ),
        )
        text = result.text.strip()
    except Exception:
        text = ""
    text = _html.escape(text)
    attrs = 'id="description" name="description" rows="3" maxlength="700"'
    return HTMLResponse(f'<textarea {attrs} class="{css}">{text}</textarea>')


@app.get("/api/book-search")
async def book_search(
    q: str = "",
    _user: User = Depends(require_user),
):
    """Proxy OpenLibrary search for autocomplete suggestions."""
    q = q.strip()
    if len(q) < 3:
        return []

    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            resp = await client.get(
                "https://openlibrary.org/search.json",
                params={
                    "title": q,
                    "lang": "eng",
                    "limit": 5,
                    "fields": "title,author_name,number_of_pages_median",
                },
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return []

    results = []
    for doc in data.get("docs", [])[:5]:
        title = doc.get("title", "")
        authors = doc.get("author_name", [])
        pages = doc.get("number_of_pages_median")
        results.append(
            {
                "title": title,
                "author": authors[0] if authors else "",
                "page_count": pages,
            }
        )
    return results


@app.get("/partials/waiting-on", response_class=HTMLResponse)
async def waiting_on_partial(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_user),
):
    season = await crud.get_active_season(db)
    if season is None:
        return HTMLResponse("")

    if season.state == SeasonState.submit:
        waiting = await crud.users_who_havent_submitted(db, season.id)
    elif season.state == SeasonState.ranking:
        waiting = await crud.users_who_havent_ranked(db, season.id)
    elif season.state == SeasonState.bracket:
        current_round = await crud.get_current_bracket_round(db, season.id)
        waiting = await crud.users_who_havent_voted_round(db, season.id, current_round)
    else:
        waiting = []

    return templates.TemplateResponse(
        "partials/waiting_on.html",
        {"request": request, "waiting_on": waiting},
    )


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    read_books = await crud.get_all_read_books(db)
    pending_read_books = await crud.get_pending_read_books(db)
    all_seasons = await crud.get_all_seasons_with_books(db)
    all_users = await crud.get_all_users(db)
    active_season = await crud.get_active_season(db)

    season_participants = []
    season_non_participants = []
    if active_season:
        season_participants = await crud.get_participants_for_season(db, active_season.id)
        participant_ids = {u.id for u in season_participants}
        season_non_participants = [u for u in all_users if u.id not in participant_ids]

    # Users whose emails aren't covered by the ALLOWED_EMAILS env var.
    # These users can still log in (DB membership grants access), but if
    # the admin thinks ALLOWED_EMAILS is the gatekeeper they should know.
    # Only computed when ALLOWED_EMAILS is actually set (empty = allow all).
    allowlist_gaps = (
        [u for u in all_users if not settings.is_email_allowed(u.email)]
        if settings.allowed_emails.strip()
        else []
    )

    # Check if most recent complete season has a meetup
    latest_complete = await crud.get_most_recent_complete_season(db)
    has_meetup = False
    if latest_complete:
        existing = await crud.get_active_meetup(db)
        has_meetup = existing is not None

    # God mode context — state-aware data for admin-on-behalf-of-user actions
    god_mode: dict = {}
    if active_season and active_season.state != SeasonState.complete:
        if active_season.state == SeasonState.submit:
            god_mode["not_submitted"] = await crud.users_who_havent_submitted(db, active_season.id)
        elif active_season.state == SeasonState.ranking:
            god_mode["not_ranked"] = await crud.users_who_havent_ranked(db, active_season.id)
            god_mode["books"] = await crud.get_books_for_season(db, active_season.id)
        elif active_season.state == SeasonState.bracket:
            current_round = await crud.get_current_bracket_round(db, active_season.id)
            god_mode["not_voted"] = await crud.users_who_havent_voted_round(
                db, active_season.id, current_round
            )
            god_mode["matchups"] = await crud.get_matchups_for_round(
                db, active_season.id, current_round
            )
            god_mode["current_round"] = current_round

    return templates.TemplateResponse(
        "admin.html",
        {
            "request": request,
            "user": user,
            "read_books": read_books,
            "pending_read_books": pending_read_books,
            "all_seasons": all_seasons,
            "all_users": all_users,
            "active_season": active_season,
            "season_participants": season_participants,
            "season_non_participants": season_non_participants,
            "allowlist_gaps": allowlist_gaps,
            "god_mode": god_mode,
            "latest_complete": latest_complete,
            "has_meetup": has_meetup,
            "promotion_count": settings.promotion_count,
        },
    )


@app.post("/admin/create-meetup", response_class=HTMLResponse)
async def admin_create_meetup(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Manually create a meetup poll for the most recent completed season."""
    from app.state import _next_weekday_at

    season = await crud.get_most_recent_complete_season(db)
    if not season:
        return RedirectResponse("/admin", status_code=302)

    existing = await crud.get_active_meetup(db)
    if existing and existing.season_id == season.id:
        return RedirectResponse("/admin", status_code=302)

    deadline = datetime.utcnow() + timedelta(weeks=settings.meetup_deadline_weeks)
    meetup = await crud.create_meetup(db, season.id, deadline)

    if settings.meetup_default_locations.strip():
        event_dt = _next_weekday_at(
            deadline, settings.meetup_default_day, settings.meetup_default_time
        )
        for loc in settings.meetup_default_locations.split(","):
            loc = loc.strip()
            if loc:
                await crud.create_meetup_option(db, meetup.id, user.id, event_dt, loc)

    return RedirectResponse("/admin", status_code=302)


# ---------------------------------------------------------------------------
# God Mode — admin acts on behalf of any user
# ---------------------------------------------------------------------------


@app.post("/admin/god-mode/submit", response_class=HTMLResponse)
async def god_mode_submit(
    user_id: int = Form(...),
    title: str = Form(...),
    author: str = Form(...),
    page_count: int = Form(...),
    description: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    season = await crud.get_active_season(db)
    if season is None or season.state != SeasonState.submit:
        return RedirectResponse("/admin", status_code=302)

    existing = await crud.get_book_submitted_by_user(db, user_id, season.id)
    if existing:
        return RedirectResponse("/admin", status_code=302)

    if page_count > season.page_limit:
        return RedirectResponse("/admin", status_code=302)

    blocked, _ = await crud.is_book_blocked(db, title, author, season.id)
    if blocked:
        return RedirectResponse("/admin", status_code=302)

    await crud.create_book(
        db, title, author, page_count, user_id, season.id, description=description or None
    )
    await state.maybe_advance_from_submit(db, season)
    return RedirectResponse("/admin", status_code=302)


@app.post("/admin/god-mode/rank", response_class=HTMLResponse)
async def god_mode_rank(
    request: Request,
    user_id: int = Form(...),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    season = await crud.get_active_season(db)
    if season is None or season.state != SeasonState.ranking:
        return RedirectResponse("/admin", status_code=302)

    existing = await crud.get_borda_votes_for_user(db, user_id, season.id)
    if existing:
        return RedirectResponse("/admin", status_code=302)

    form_data = await request.form()
    books = await crud.get_books_for_season(db, season.id)
    try:
        ranked: dict[int, int] = {}
        for book in books:
            rank_val = form_data.get(f"rank_{book.id}")
            if rank_val is None:
                raise ValueError(f"Missing rank for book {book.id}")
            ranked[book.id] = int(rank_val)
    except (ValueError, TypeError):
        return RedirectResponse("/admin", status_code=302)

    ranks = list(ranked.values())
    n = len(books)
    if sorted(ranks) != list(range(1, n + 1)):
        return RedirectResponse("/admin", status_code=302)

    ordered_ids = [book_id for book_id, _ in sorted(ranked.items(), key=lambda x: x[1])]
    await crud.save_borda_votes(db, user_id, season.id, ordered_ids)
    await state.maybe_advance_from_ranking(db, season)
    return RedirectResponse("/admin", status_code=302)


@app.post("/admin/god-mode/bracket-vote", response_class=HTMLResponse)
async def god_mode_bracket_vote(
    user_id: int = Form(...),
    matchup_id: int = Form(...),
    book_id: int = Form(...),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    season = await crud.get_active_season(db)
    if season is None or season.state != SeasonState.bracket:
        return RedirectResponse("/admin", status_code=302)

    matchup = await crud.get_matchup_by_id(db, matchup_id)
    if matchup is None or matchup.season_id != season.id:
        return RedirectResponse("/admin", status_code=302)

    current_round = await crud.get_current_bracket_round(db, season.id)
    if matchup.round != current_round:
        return RedirectResponse("/admin", status_code=302)

    existing = await crud.get_bracket_vote(db, user_id, matchup_id)
    if existing:
        return RedirectResponse("/admin", status_code=302)

    if book_id not in (matchup.book_a_id, matchup.book_b_id):
        return RedirectResponse("/admin", status_code=302)

    await crud.save_bracket_vote(db, user_id, matchup_id, book_id)
    await state.maybe_advance_bracket_round(db, season)
    return RedirectResponse("/admin", status_code=302)


@app.post("/admin/god-mode/auto-vote", response_class=HTMLResponse)
async def god_mode_auto_vote(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Randomly vote for every user who hasn't voted yet in the current bracket round."""
    import random

    season = await crud.get_active_season(db)
    if season is None or season.state != SeasonState.bracket:
        return RedirectResponse("/admin", status_code=302)

    current_round = await crud.get_current_bracket_round(db, season.id)
    not_voted = await crud.users_who_havent_voted_round(db, season.id, current_round)
    matchups = await crud.get_matchups_for_round(db, season.id, current_round)

    for user in not_voted:
        for m in matchups:
            if m.book_a_id == m.book_b_id:
                continue  # bye
            existing = await crud.get_bracket_vote(db, user.id, m.id)
            if existing:
                continue
            pick = random.choice([m.book_a_id, m.book_b_id])
            await crud.save_bracket_vote(db, user.id, m.id, pick)

    await state.maybe_advance_bracket_round(db, season)
    return RedirectResponse("/admin", status_code=302)


@app.post("/admin/god-mode/copy-submissions", response_class=HTMLResponse)
async def god_mode_copy_submissions(
    source_season_id: int = Form(...),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Copy book submissions from a previous season into the active season."""
    season = await crud.get_active_season(db)
    if season is None or season.state != SeasonState.submit:
        return RedirectResponse("/admin", status_code=302)

    source_books = await crud.get_books_for_season(db, source_season_id)
    participants = await crud.get_participants_for_season(db, season.id)
    participant_ids = {u.id for u in participants}

    for book in source_books:
        if book.submitter_id not in participant_ids:
            continue
        existing = await crud.get_book_submitted_by_user(db, book.submitter_id, season.id)
        if existing:
            continue
        if book.page_count > season.page_limit:
            continue
        await crud.create_book(
            db,
            title=book.title,
            author=book.author,
            page_count=book.page_count,
            submitter_id=book.submitter_id,
            season_id=season.id,
            description=book.description,
        )

    await state.maybe_advance_from_submit(db, season)
    return RedirectResponse("/admin", status_code=302)


@app.post("/admin/season", response_class=HTMLResponse)
async def create_season(
    name: str = Form(...),
    page_limit: int = Form(400),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    season = await crud.create_season(db, name, page_limit)
    all_users = await crud.get_all_users(db)
    for u in all_users:
        await crud.add_participant(db, season.id, u.id)

    # Auto-promote top books from the most recent completed season
    if settings.promotion_count > 0:
        prior = await crud.get_most_recent_complete_season(db)
        if prior:
            await crud.promote_books_to_season(db, prior.id, season.id, settings.promotion_count)

    return RedirectResponse("/admin", status_code=302)


@app.post("/admin/read-books", response_class=HTMLResponse)
async def add_read_book(
    title: str = Form(...),
    author: str = Form(...),
    won: bool = Form(False),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    await crud.add_read_book(db, title, author, won, user.id)
    return RedirectResponse("/admin", status_code=302)


@app.post("/admin/read-books/{read_book_id}/delete", response_class=HTMLResponse)
async def delete_read_book(
    read_book_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    await crud.delete_read_book(db, read_book_id)
    return RedirectResponse("/admin", status_code=302)


@app.post("/admin/read-books/{read_book_id}/approve", response_class=HTMLResponse)
async def approve_read_book(
    read_book_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    await crud.approve_read_book(db, read_book_id)
    return RedirectResponse("/admin", status_code=302)


@app.post("/admin/read-books/{read_book_id}/reject", response_class=HTMLResponse)
async def reject_read_book(
    read_book_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    await crud.delete_read_book(db, read_book_id)
    return RedirectResponse("/admin", status_code=302)


@app.post("/admin/users/{user_id}/toggle-admin", response_class=HTMLResponse)
async def toggle_admin(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    target = await crud.get_user_by_id(db, user_id)
    if target and target.id != current_user.id:
        target.is_admin = not target.is_admin
        await db.commit()
    return RedirectResponse("/admin", status_code=302)


@app.post("/admin/users/add", response_class=HTMLResponse)
async def add_user(
    name: str = Form(...),
    email: str = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    await crud.create_user(db, name, email)
    return RedirectResponse("/admin", status_code=302)


@app.post("/admin/users/{user_id}/delete", response_class=HTMLResponse)
async def delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    if user_id != current_user.id:
        await crud.delete_user(db, user_id, reassign_read_books_to=current_user.id)
    return RedirectResponse("/admin", status_code=302)


@app.post("/admin/season/{season_id}/delete", response_class=HTMLResponse)
async def delete_season(
    season_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    await crud.delete_season(db, season_id)
    return RedirectResponse("/admin", status_code=302)


@app.post("/admin/season/{season_id}/advance", response_class=HTMLResponse)
async def force_advance_season(
    season_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    season = await crud.get_season_by_id(db, season_id)
    if season is None:
        return RedirectResponse("/admin", status_code=302)

    if season.state == SeasonState.submit:
        await crud.set_season_state(db, season, SeasonState.ranking)
    elif season.state == SeasonState.ranking:
        books = await crud.get_books_for_season(db, season.id)
        if len(books) >= 2:
            votes = await crud.get_all_borda_votes_for_season(db, season.id)
            prior_nominations = await crud.get_prior_nomination_counts(db, season.id)
            seed_map = voting.compute_borda_seeds(books, votes, prior_nominations)
            await crud.save_seeds(db, season.id, seed_map)
            first_round = voting.build_first_round_matchups(season.id, seed_map)
            await crud.create_matchups(db, first_round)
            await crud.set_season_state(db, season, SeasonState.bracket)
    elif season.state == SeasonState.bracket:
        await crud.set_season_state(db, season, SeasonState.complete)

    return RedirectResponse("/admin", status_code=302)


@app.post("/admin/season/{season_id}/participants/add", response_class=HTMLResponse)
async def admin_add_participant(
    season_id: int,
    user_id: int = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    await crud.add_participant(db, season_id, user_id)
    return RedirectResponse("/admin", status_code=302)


@app.post(
    "/admin/season/{season_id}/participants/remove/{user_id}",
    response_class=HTMLResponse,
)
async def admin_remove_participant(
    season_id: int,
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    await crud.remove_participant(db, season_id, user_id)
    season = await crud.get_season_by_id(db, season_id)
    if season:
        await state.maybe_advance_from_submit(db, season)
        await state.maybe_advance_from_ranking(db, season)
    return RedirectResponse("/admin", status_code=302)


@app.post("/admin/books/{book_id}/edit", response_class=HTMLResponse)
async def edit_book(
    book_id: int,
    title: str = Form(...),
    author: str = Form(...),
    page_count: int = Form(...),
    description: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    await crud.update_book(db, book_id, title, author, page_count, description=description or None)
    return RedirectResponse("/admin", status_code=302)


@app.post("/admin/books/{book_id}/delete", response_class=HTMLResponse)
async def delete_book(
    book_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    await crud.delete_book(db, book_id)
    return RedirectResponse("/admin", status_code=302)


# ---------------------------------------------------------------------------
# User settings
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Meetup scheduling
# ---------------------------------------------------------------------------


@app.get("/meetup", response_class=HTMLResponse)
async def meetup_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_user),
):
    meetup = await crud.get_active_meetup(db)
    if meetup and not meetup.finalized_option_id and datetime.utcnow() > meetup.deadline:
        winner = await crud.finalize_meetup(db, meetup)
        if winner:
            participants = await crud.get_participants_for_season(db, meetup.season_id)
            emails = [u.email for u in participants if u.email and u.email_notifications]
            await notify.notify_all(
                emails=emails,
                discord_msg=(
                    f"📅 Meetup decided! "
                    f"{winner.event_datetime.strftime('%A, %b %d at %-I:%M %p')} "
                    f"at {winner.location}"
                ),
                email_subject="Meetup time is set!",
                email_body=(
                    f"<h2>We're meeting up!</h2>"
                    f"<p>{winner.event_datetime.strftime('%A, %b %d at %-I:%M %p')} "
                    f"at {winner.location}</p>"
                ),
            )
            # Reload to get updated finalized_option
            meetup = await crud.get_active_meetup(db)

    voted_ids: set[int] = set()
    winner_book = None
    if meetup:
        voted_ids = {
            v.option_id for opt in meetup.options for v in opt.votes if v.user_id == user.id
        }
        winner_book = await crud.get_winner_book_for_season(db, meetup.season_id)

    # Stable order by creation time so cards don't jump around after voting.
    # Vote counts are shown on each card — no need to reorder by popularity.
    sorted_options = sorted(meetup.options, key=lambda o: o.created_at) if meetup else []

    return templates.TemplateResponse(
        "meetup.html",
        {
            "request": request,
            "user": user,
            "meetup": meetup,
            "sorted_options": sorted_options,
            "voted_ids": voted_ids,
            "winner_book": winner_book,
        },
    )


@app.post("/meetup/option", response_class=HTMLResponse)
async def add_meetup_option(
    event_month: int = Form(...),
    event_day: int = Form(...),
    event_time: str = Form("19:00"),
    location: str = Form(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_user),
):
    meetup = await crud.get_active_meetup_shallow(db)
    if not meetup or meetup.finalized_option_id or datetime.utcnow() > meetup.deadline:
        return RedirectResponse("/meetup", status_code=302)
    try:
        hour, minute = (int(x) for x in event_time.split(":"))
        now = datetime.utcnow()
        year = now.year
        # In Nov/Dec, if proposed month is Jan/Feb, assume next year
        if now.month >= 11 and event_month <= 2:
            year += 1
        event_dt = datetime(year, event_month, event_day, hour, minute)
    except (ValueError, TypeError):
        return RedirectResponse("/meetup", status_code=302)
    if event_dt < datetime.utcnow():
        return RedirectResponse("/meetup", status_code=302)
    await crud.create_meetup_option(db, meetup.id, user.id, event_dt, location.strip())
    return RedirectResponse("/meetup", status_code=302)


@app.post("/meetup/vote/{option_id}", response_class=HTMLResponse)
async def toggle_meetup_vote(
    option_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_user),
):
    # Pure scalar check — no ORM objects loaded into the session at all,
    # so no cascade/relationship interference can occur during commit.
    if not await crud.is_meetup_option_votable(db, option_id):
        return RedirectResponse("/meetup", status_code=302)
    await crud.toggle_meetup_vote(db, option_id, user.id)
    return RedirectResponse("/meetup", status_code=302)


@app.post("/meetup/option/{option_id}/delete", response_class=HTMLResponse)
async def delete_meetup_option(
    option_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_user),
):
    meetup = await crud.get_active_meetup_shallow(db)
    if not meetup or meetup.finalized_option_id or datetime.utcnow() > meetup.deadline:
        return RedirectResponse("/meetup", status_code=302)
    await crud.delete_meetup_option(db, option_id, user.id)
    return RedirectResponse("/meetup", status_code=302)


@app.post("/meetup/finalize", response_class=HTMLResponse)
async def finalize_meetup(
    option_id: int = Form(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    meetup = await crud.get_active_meetup_shallow(db)
    if not meetup or meetup.finalized_option_id:
        return RedirectResponse("/meetup", status_code=302)
    await crud.admin_finalize_meetup(db, meetup, option_id)
    # Reload to get the finalized option details
    meetup = await crud.get_active_meetup(db)
    if meetup and meetup.finalized_option:
        opt = meetup.finalized_option
        participants = await crud.get_participants_for_season(db, meetup.season_id)
        emails = [u.email for u in participants if u.email and u.email_notifications]
        await notify.notify_all(
            emails=emails,
            discord_msg=(
                f"📅 Meetup decided! "
                f"{opt.event_datetime.strftime('%A, %b %d at %-I:%M %p')} "
                f"at {opt.location}"
            ),
            email_subject="Meetup time is set!",
            email_body=(
                f"<h2>We're meeting up!</h2>"
                f"<p>{opt.event_datetime.strftime('%A, %b %d at %-I:%M %p')} "
                f"at {opt.location}</p>"
            ),
        )
    return RedirectResponse("/meetup", status_code=302)


@app.post("/meetup/deadline", response_class=HTMLResponse)
async def update_meetup_deadline(
    deadline_date: str = Form(...),
    deadline_time: str = Form("23:59"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    meetup = await crud.get_active_meetup_shallow(db)
    if not meetup or meetup.finalized_option_id:
        return RedirectResponse("/meetup", status_code=302)
    try:
        hour, minute = (int(x) for x in deadline_time.split(":"))
        year, month, day = (int(x) for x in deadline_date.split("-"))
        new_deadline = datetime(year, month, day, hour, minute)
    except (ValueError, TypeError):
        return RedirectResponse("/meetup", status_code=302)
    await crud.update_meetup_deadline(db, meetup, new_deadline)
    return RedirectResponse("/meetup", status_code=302)


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    user: User = Depends(require_user),
):
    saved = request.query_params.get("saved") == "1"
    return templates.TemplateResponse(
        "settings.html",
        {"request": request, "user": user, "saved": saved},
    )


@app.post("/settings", response_class=HTMLResponse)
async def save_settings(
    display_name: str = Form(""),
    email_notifications: str = Form("off"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_user),
):
    db_user = await db.get(User, user.id)
    db_user.display_name = display_name.strip() or None
    db_user.email_notifications = email_notifications == "on"
    await db.commit()
    return RedirectResponse("/settings?saved=1", status_code=302)


# ---------------------------------------------------------------------------
# Feature ideas
# ---------------------------------------------------------------------------


@app.get("/ideas", response_class=HTMLResponse)
async def ideas_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_user),
):
    ideas = await crud.get_all_ideas(db)
    upvoted_ids = await crud.get_user_upvoted_idea_ids(db, user.id)
    idea_count = await crud.get_active_idea_count_for_user(db, user.id)
    return templates.TemplateResponse(
        "ideas.html",
        {
            "request": request,
            "user": user,
            "ideas": ideas,
            "upvoted_ids": upvoted_ids,
            "idea_count": idea_count,
            "max_ideas": 3,
        },
    )


@app.post("/ideas", response_class=HTMLResponse)
async def submit_idea(
    title: str = Form(...),
    description: str = Form(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_user),
):
    title = title.strip()
    description = description.strip()

    if not title or not description:
        return RedirectResponse("/ideas", status_code=302)

    count = await crud.get_active_idea_count_for_user(db, user.id)
    if count >= 3:
        return RedirectResponse("/ideas", status_code=302)

    if await crud.has_duplicate_idea(db, user.id, title):
        return RedirectResponse("/ideas", status_code=302)

    complexity = None
    try:
        from google import genai as google_genai

        client = google_genai.Client(api_key=settings.gemini_api_key)
        result = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=(
                "A small book club web app (FastAPI, SQLAlchemy, Jinja2, HTMX, Tailwind). "
                "Models: User, Season, Book, ReadBook, BordaVote, Seed, BracketMatchup, "
                "BracketVote, SeasonParticipant, FeatureIdea, IdeaUpvote. "
                f"A member suggested this feature: '{title}: {description}'. "
                "Write a short assessment in this exact format (no extra text):\n"
                "[RATING] — [explanation in 20 words or less mentioning specific "
                "tables, routes, or templates involved]\n"
                "RATING must be one of: Quick Win, Moderate, Large, Ambitious."
            ),
        )
        raw = result.text.strip()
        for rating in ("Quick Win", "Moderate", "Large", "Ambitious"):
            if raw.startswith(rating):
                complexity = raw
                break
    except Exception:
        pass

    await crud.create_idea(db, user.id, title, description, complexity)
    return RedirectResponse("/ideas", status_code=302)


@app.post("/ideas/{idea_id}/upvote", response_class=HTMLResponse)
async def upvote_idea(
    idea_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_user),
):
    await crud.toggle_upvote(db, idea_id, user.id)
    return RedirectResponse("/ideas", status_code=302)


@app.post("/ideas/{idea_id}/delete", response_class=HTMLResponse)
async def delete_idea(
    idea_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    await crud.delete_idea(db, idea_id)
    return RedirectResponse("/ideas", status_code=302)


@app.post("/ideas/{idea_id}/status", response_class=HTMLResponse)
async def update_idea_status(
    idea_id: int,
    status: str = Form(...),
    admin_note: str = Form(""),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    try:
        idea_status = IdeaStatus(status)
    except ValueError:
        return RedirectResponse("/ideas", status_code=302)
    await crud.update_idea_status(db, idea_id, idea_status, admin_note.strip())
    return RedirectResponse("/ideas", status_code=302)


# ---------------------------------------------------------------------------
# Member stats (admin-only)
# ---------------------------------------------------------------------------


@app.get("/admin/members/{user_id}", response_class=HTMLResponse)
async def admin_member_stats(
    user_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    target = await crud.get_user_by_id(db, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found.")

    season_count = await crud.get_season_count_for_user(db, user_id)
    books = await crud.get_books_by_user(db, user_id)
    winning_ids = await crud.get_winning_book_ids(db)
    correct, total = await crud.get_bracket_vote_accuracy(db, user_id)

    win_count = sum(1 for b in books if b.id in winning_ids)
    win_rate = (win_count / season_count * 100) if season_count > 0 else 0
    batting_avg = (correct / total * 100) if total > 0 else None

    books_with_status = [(b, b.id in winning_ids) for b in books]

    return templates.TemplateResponse(
        "admin_member_stats.html",
        {
            "request": request,
            "user": current_user,
            "target": target,
            "season_count": season_count,
            "book_count": len(books),
            "win_count": win_count,
            "win_rate": win_rate,
            "batting_avg": batting_avg,
            "correct_votes": correct,
            "total_votes": total,
            "books_with_status": books_with_status,
        },
    )
