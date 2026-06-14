"""Seed a demo season for manual QA.

Creates N pre-registered test users and a fresh season, then drives it to a
chosen stage using the *real* crud + state-machine code (so you're exercising
production logic, not a parallel fake path). For the submit/ranking/bracket
stages it deliberately leaves ONE user un-acted, so you can perform that final
step yourself in the live UI and watch the phase auto-advance.

Usage:
    make seed                         # 6 users, sitting in `submit`
    make seed STAGE=bracket USERS=8
    python -m scripts.seed_demo --stage complete --users 6 --force

Guarded by DEV_TOOLS_ENABLED (or --force) so it can't be run by accident
against a real database.
"""

import argparse
import asyncio
import random

from sqlalchemy import select

from app import crud, seed_data, state
from app.config import settings
from app.database import AsyncSessionLocal
from app.main import fetch_cover_url
from app.models import SeasonState, User

STAGES = ["submit", "ranking", "bracket", "complete"]


async def _ensure_users(db, n: int) -> list[User]:
    """Create (or reuse) n demo users with stable demo*@seed.local emails."""
    users = []
    for i in range(1, n + 1):
        email = f"demo{i}@seed.local"
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if user is None:
            user = await crud.create_user(db, f"Demo User {i}", email)
        users.append(user)
    return users


async def _submit_books(db, season, users) -> None:
    books = seed_data.pick_books(len(users), max_pages=season.page_limit)
    for user, (title, author, pages) in zip(users, books):
        if await crud.get_book_submitted_by_user(db, user.id, season.id):
            continue
        cover_url = await fetch_cover_url(title, author)
        await crud.create_book(
            db, title, author, pages, user.id, season.id, cover_url=cover_url
        )


async def _rank_books(db, season, users) -> None:
    book_ids = [b.id for b in await crud.get_books_for_season(db, season.id)]
    for user in users:
        if await crud.get_borda_votes_for_user(db, user.id, season.id):
            continue
        order = book_ids[:]
        random.shuffle(order)
        await crud.save_borda_votes(db, user.id, season.id, order)


async def _vote_round(db, season, users) -> None:
    current_round = await crud.get_current_bracket_round(db, season.id)
    if current_round == 0:
        return
    matchups = await crud.get_matchups_for_round(db, season.id, current_round)
    for user in users:
        for m in matchups:
            if m.book_a_id == m.book_b_id:  # bye
                continue
            if await crud.get_bracket_vote(db, user.id, m.id):
                continue
            await crud.save_bracket_vote(db, user.id, m.id, random.choice([m.book_a_id, m.book_b_id]))


async def _drive(db, season, users, stage: str) -> None:
    target = STAGES.index(stage)
    # Everyone acts when we need to advance PAST a phase; otherwise hold one back.
    all_but_one = users[:-1] if len(users) > 1 else users

    # --- Submit ---
    await _submit_books(db, season, users if target > STAGES.index("submit") else all_but_one)
    await state.maybe_advance_from_submit(db, season)
    if target == STAGES.index("submit"):
        return

    # --- Ranking ---
    await _rank_books(db, season, users if target > STAGES.index("ranking") else all_but_one)
    await state.maybe_advance_from_ranking(db, season)
    if target == STAGES.index("ranking"):
        return

    # --- Bracket ---
    if target == STAGES.index("bracket"):
        # Populate round 1 but leave one straggler so it sits mid-round.
        await _vote_round(db, season, all_but_one)
        await state.maybe_advance_bracket_round(db, season)
        return

    # --- Complete: vote every round to a winner ---
    for _ in range(20):  # safety bound; far more rounds than any real bracket
        if season.state != SeasonState.bracket:
            break
        await _vote_round(db, season, users)
        await state.maybe_advance_bracket_round(db, season)


async def main(stage: str, n_users: int, name: str, page_limit: int) -> None:
    async with AsyncSessionLocal() as db:
        active = await crud.get_active_season(db)
        if active and active.state != SeasonState.complete:
            print(f"⚠️  Heads up: '{active.name}' is still active ({active.state.value}). "
                  "The new demo season will become the active one.")

        users = await _ensure_users(db, n_users)
        season = await crud.create_season(db, name, page_limit)
        for u in users:
            await crud.add_participant(db, season.id, u.id)
        print(f"Created season '{season.name}' (#{season.id}) with {len(users)} users.")

        await _drive(db, season, users, stage)
        await db.refresh(season)

    straggler = users[-1] if len(users) > 1 and stage != "complete" else None
    print(f"✅ Season is now in: {season.state.value}")
    if straggler:
        print(f"   Left {straggler.visible_name} ({straggler.email}) un-acted so you can "
              "finish this phase in the UI and watch it advance.")
    print(f"   View it at {settings.app_base_url}/admin")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed a demo season for manual QA.")
    parser.add_argument("--stage", choices=STAGES, default="submit")
    parser.add_argument("--users", type=int, default=6)
    parser.add_argument("--name", default="Demo Season")
    parser.add_argument("--page-limit", type=int, default=400)
    parser.add_argument("--force", action="store_true", help="run even if DEV_TOOLS_ENABLED is off")
    args = parser.parse_args()

    if not settings.dev_tools_enabled and not args.force:
        raise SystemExit(
            "Refusing to run: DEV_TOOLS_ENABLED is off. Set DEV_TOOLS_ENABLED=true in your "
            ".env (dev only) or pass --force if you're sure this is a dev database."
        )

    asyncio.run(main(args.stage, args.users, args.name, args.page_limit))
