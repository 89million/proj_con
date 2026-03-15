"""FastAPI application — all routes."""

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import crud, state, voting
from app.auth import (
    build_authorization_url,
    create_session_token,
    exchange_code_for_user_info,
    get_current_user,
    get_or_create_user,
)
from app.config import settings
from app.database import get_db
from app.models import SeasonState, User

app = FastAPI(title="Book Club")

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

_ROUND_LABELS = ["Final", "Semifinals", "Quarterfinals", "Round of 16", "Round of 32"]


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

    # No active season — redirect to winner page if any season has completed
    complete = await crud.get_most_recent_complete_season(db)
    if complete is not None:
        return RedirectResponse("/complete", status_code=302)

    # Truly no history — show the "no season" page (admin sees start button)
    return templates.TemplateResponse("no_season.html", {"request": request, "user": user})


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

    my_book = await crud.get_book_submitted_by_user(db, user.id, season.id)
    waiting_on = await crud.users_who_havent_submitted(db, season.id)
    all_submissions = await crud.get_books_for_season(db, season.id)

    return templates.TemplateResponse(
        "submit.html",
        {
            "request": request,
            "user": user,
            "season": season,
            "my_book": my_book,
            "waiting_on": waiting_on,
            "all_submissions": all_submissions,
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

    current_round = await crud.get_current_bracket_round(db, season.id)
    all_matchups = await crud.get_matchups_for_season(db, season.id)
    seeds = await crud.get_seeds_for_season(db, season.id)
    waiting_on = await crud.users_who_havent_voted_round(db, season.id, current_round)

    # Which matchups has this user voted on?
    user_votes: dict[int, int] = {}  # {matchup_id: book_id}
    for matchup in all_matchups:
        vote = await crud.get_bracket_vote(db, user.id, matchup.id)
        if vote:
            user_votes[matchup.id] = vote.book_id

    max_round = max((m.round for m in all_matchups), default=1)
    round_names = build_round_names(max_round)

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
            "user_votes": user_votes,
            "waiting_on": waiting_on,
            "round_names": round_names,
            "prior_nominations": prior_nominations,
            "matchup_tiebreakers": matchup_tiebreakers,
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
    if season:
        winner_book = await crud.get_winner_book_for_season(db, season.id)

    return templates.TemplateResponse(
        "complete.html",
        {
            "request": request,
            "user": user,
            "season": season,
            "winner_book": winner_book,
        },
    )


@app.get("/history", response_class=HTMLResponse)
async def history_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_user),
):
    complete_seasons = await crud.get_complete_seasons(db)
    seasons_with_winners = []
    for s in complete_seasons:
        winner = await crud.get_winner_book_for_season(db, s.id)
        seasons_with_winners.append((s, winner))

    return templates.TemplateResponse(
        "history.html",
        {
            "request": request,
            "user": user,
            "seasons_with_winners": seasons_with_winners,
        },
    )


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
    max_round = max((m.round for m in matchups), default=1)
    round_names = build_round_names(max_round)

    # Borda scores: (N_books - rank) per vote, summed per book
    all_borda_votes = await crud.get_all_borda_votes_for_season(db, season_id)
    n_books = len(books)
    borda_scores: dict[int, int] = {}
    for vote in all_borda_votes:
        borda_scores[vote.book_id] = borda_scores.get(vote.book_id, 0) + (n_books - vote.rank)

    prior_nominations = await crud.get_prior_nomination_counts(db, season_id)
    matchup_ties = {m.id: matchup_tiebreaker(m, prior_nominations) for m in matchups}
    seed_ties = seed_tiebreakers(seeds, borda_scores, prior_nominations)

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
            "matchup_tiebreakers": matchup_ties,
            "seed_tiebreakers": seed_ties,
        },
    )


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
    import html

    text = html.escape(text)
    attrs = 'id="description" name="description" rows="3" maxlength="700"'
    return HTMLResponse(f'<textarea {attrs} class="{css}">{text}</textarea>')


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

    return templates.TemplateResponse(
        "admin.html",
        {
            "request": request,
            "user": user,
            "read_books": read_books,
            "all_seasons": all_seasons,
            "all_users": all_users,
            "active_season": active_season,
            "season_participants": season_participants,
            "season_non_participants": season_non_participants,
            "allowlist_gaps": allowlist_gaps,
        },
    )


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
