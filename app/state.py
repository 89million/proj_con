"""State machine: check transition conditions and auto-advance seasons."""

from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app import crud, notify, voting
from app.config import settings
from app.models import ReadBook, Season, SeasonState

# Day-of-week name → weekday int (Monday=0)
_WEEKDAY_MAP = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


def _next_weekday_at(after: datetime, day: str, time_str: str) -> datetime:
    """Find the first occurrence of `day` at `time_str` on or after `after`."""
    target_wd = _WEEKDAY_MAP.get(day.lower(), 4)  # default Friday
    hour, minute = (int(x) for x in time_str.split(":"))
    current_wd = after.weekday()
    days_ahead = (target_wd - current_wd) % 7
    if days_ahead == 0 and after.hour >= hour:
        days_ahead = 7
    result = after.replace(hour=hour, minute=minute, second=0, microsecond=0) + timedelta(
        days=days_ahead
    )
    return result


async def _participant_emails(db: AsyncSession, season_id: int) -> list[str]:
    participants = await crud.get_participants_for_season(db, season_id)
    return [u.email for u in participants if u.email and u.email_notifications]


async def maybe_advance_from_submit(db: AsyncSession, season: Season) -> bool:
    """Advance submit → ranking when every participant has submitted."""
    if season.state != SeasonState.submit:
        return False

    submissions = await crud.count_submissions(db, season.id)
    total_participants = await crud.count_participants(db, season.id)

    if total_participants > 0 and submissions >= total_participants:
        await crud.set_season_state(db, season, SeasonState.ranking)
        emails = await _participant_emails(db, season.id)
        url = settings.app_base_url
        await notify.notify_all(
            emails=emails,
            discord_msg=(
                f"📚 **{season.name}** — All books are in! "
                f"Time to rank your favorites. Head to the site and submit your ranking."
            ),
            email_subject=f"{season.name} — Time to rank!",
            email_body=(
                f"<h2>All books are in for {season.name}!</h2>"
                f"<p>Time to rank your favorites. The book with the most Borda points "
                f"gets the top bracket seed.</p>"
                f'<p><a href="{url}/ranking">Submit your ranking →</a></p>'
            ),
        )
        return True
    return False


async def maybe_advance_from_ranking(db: AsyncSession, season: Season) -> bool:
    """Advance ranking → bracket when every participant has ranked.

    Also computes Borda seeds and creates the first-round bracket matchups.
    """
    if season.state != SeasonState.ranking:
        return False

    total_participants = await crud.count_participants(db, season.id)
    voters = await crud.count_borda_voters(db, season.id)

    if total_participants > 0 and voters >= total_participants:
        books = await crud.get_books_for_season(db, season.id)

        # Need at least 2 books to run a bracket
        if len(books) < 2:
            return False

        votes = await crud.get_all_borda_votes_for_season(db, season.id)
        prior_nominations = await crud.get_prior_nomination_counts(db, season.id)
        seed_map = voting.compute_borda_seeds(books, votes, prior_nominations)

        await crud.save_seeds(db, season.id, seed_map)

        # Relegate bottom N books (N = promotion_count) from the bracket
        relegated_ids = voting.get_relegated_book_ids(seed_map, settings.promotion_count)
        bracket_seed_map = {bid: s for bid, s in seed_map.items() if bid not in relegated_ids}
        # Re-number seeds contiguously for bracket generation
        sorted_bracket = sorted(bracket_seed_map.items(), key=lambda x: x[1])
        bracket_seed_map = {bid: i + 1 for i, (bid, _) in enumerate(sorted_bracket)}

        first_round = voting.build_first_round_matchups(season.id, bracket_seed_map)
        await crud.create_matchups(db, first_round)

        await crud.set_season_state(db, season, SeasonState.bracket)
        emails = await _participant_emails(db, season.id)
        url = settings.app_base_url
        await notify.notify_all(
            emails=emails,
            discord_msg=(
                f"🏆 **{season.name}** — Rankings are locked in! "
                f"The tournament bracket is live. Cast your first-round votes!"
            ),
            email_subject=f"{season.name} — The bracket is live!",
            email_body=(
                f"<h2>The tournament bracket for {season.name} is live!</h2>"
                f"<p>Rankings are locked in and seeds have been assigned. "
                f"Time to cast your first-round votes.</p>"
                f'<p><a href="{url}/bracket">Vote now →</a></p>'
            ),
        )
        return True
    return False


async def maybe_advance_bracket_round(db: AsyncSession, season: Season) -> bool:
    """Resolve the current bracket round if all participants have voted on real matchups.

    Byes (book_a == book_b) are already pre-resolved and don't require votes.
    When only 1 unique winner remains after resolving a round, the season is complete.
    """
    if season.state != SeasonState.bracket:
        return False

    current_round = await crud.get_current_bracket_round(db, season.id)
    if current_round == 0:
        # All existing matchups are resolved but season isn't complete —
        # rebuild the next round from the latest resolved round.
        latest_round = await crud.get_latest_bracket_round(db, season.id)
        if latest_round == 0:
            return False
        matchups = await crud.get_matchups_for_round(db, season.id, latest_round)
        all_winner_ids = list(dict.fromkeys(m.winner_id for m in matchups))
        if len(all_winner_ids) <= 1:
            return False  # should already be complete
        next_round_matchups = voting.build_next_round_matchups(
            season.id, matchups, latest_round + 1
        )
        await crud.create_matchups(db, next_round_matchups)
        return True

    matchups = await crud.get_matchups_for_round(db, season.id, current_round)

    # Separate real matchups from pre-resolved byes
    real_matchups = [m for m in matchups if m.book_a_id != m.book_b_id and m.winner_id is None]

    if real_matchups:
        total_participants = await crud.count_participants(db, season.id)
        voters_done = await crud.count_bracket_voters_for_round(db, season.id, current_round)
        if total_participants == 0 or voters_done < total_participants:
            return False

        # Resolve winners for real matchups
        prior_nominations = await crud.get_prior_nomination_counts(db, season.id)
        for matchup in real_matchups:
            winner_id = voting.resolve_matchup_winner(matchup, matchup.votes, prior_nominations)
            await crud.set_matchup_winner(db, matchup, winner_id)

    # Reload with all winner_ids now set
    matchups = await crud.get_matchups_for_round(db, season.id, current_round)
    all_winner_ids = list(dict.fromkeys(m.winner_id for m in matchups))  # ordered, deduped

    emails = await _participant_emails(db, season.id)
    url = settings.app_base_url

    if len(all_winner_ids) == 1:
        # One book remains — season complete
        winner_book_id = all_winner_ids[0]
        books = await crud.get_books_for_season(db, season.id)
        winner_book = next(b for b in books if b.id == winner_book_id)

        all_users = await crud.get_all_users(db)
        admin = next((u for u in all_users if u.is_admin), all_users[0])

        rb = ReadBook(
            title=winner_book.title,
            author=winner_book.author,
            won=True,
            added_by=admin.id,
        )
        db.add(rb)
        await crud.set_season_state(db, season, SeasonState.complete)
        # Auto-create meetup poll
        deadline = datetime.utcnow() + timedelta(weeks=settings.meetup_deadline_weeks)
        meetup = await crud.create_meetup(db, season.id, deadline)

        # Seed with default location options
        if settings.meetup_default_locations.strip():
            event_dt = _next_weekday_at(
                deadline, settings.meetup_default_day, settings.meetup_default_time
            )
            for loc in settings.meetup_default_locations.split(","):
                loc = loc.strip()
                if loc:
                    await crud.create_meetup_option(db, meetup.id, admin.id, event_dt, loc)

        await notify.notify_all(
            emails=emails,
            discord_msg=(
                f"🎉 **{season.name}** is complete! "
                f"The winner is **{winner_book.title}** by {winner_book.author}! "
                f"Vote on when to meet: {url}/meetup"
            ),
            email_subject=f"{season.name} — We have a winner!",
            email_body=(
                f"<h2>{season.name} is complete!</h2>"
                f"<p>The winner is <strong>{winner_book.title}</strong> "
                f"by {winner_book.author}.</p>"
                f"<p>Time to start reading!</p>"
                f'<p><a href="{url}/complete">See the results →</a></p>'
                f'<p><a href="{url}/meetup">Vote on meetup time →</a></p>'
            ),
        )
    else:
        # Advance to next round
        next_round_matchups = voting.build_next_round_matchups(
            season.id, matchups, current_round + 1
        )
        await crud.create_matchups(db, next_round_matchups)
        await notify.notify_all(
            emails=emails,
            discord_msg=(
                f"⚔️ **{season.name}** — Round {current_round} is decided! "
                f"The next round is now open for voting."
            ),
            email_subject=f"{season.name} — Next round is live!",
            email_body=(
                f"<h2>Round {current_round} is decided!</h2>"
                f"<p>The next round of the {season.name} bracket is now open. "
                f"Cast your votes!</p>"
                f'<p><a href="{url}/bracket">Vote now →</a></p>'
            ),
        )

    return True
