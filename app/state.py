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


async def maybe_advance_from_submit(
    db: AsyncSession, season: Season, *, force: bool = False
) -> bool:
    """Advance submit → ranking when every participant has submitted (or forced)."""
    if season.state != SeasonState.submit:
        return False

    submissions = await crud.count_submissions(db, season.id)
    total_participants = await crud.count_participants(db, season.id)

    if force or (total_participants > 0 and submissions >= total_participants):
        if season.ranking_days and not season.ranking_deadline:
            season.ranking_deadline = datetime.utcnow() + timedelta(days=season.ranking_days)
        await crud.set_season_state(db, season, SeasonState.ranking)
        emails = await _participant_emails(db, season.id)
        url = settings.app_base_url
        deadline_note = ""
        deadline_html = ""
        if season.ranking_deadline:
            dl = season.ranking_deadline.strftime("%a %b %d at %H:%M UTC")
            deadline_note = f" Deadline to rank: {dl}."
            deadline_html = (
                f"<p><strong>Deadline:</strong> {dl}. "
                f"If everyone ranks before then we'll move forward early — "
                f"otherwise rankings are locked in automatically at the deadline.</p>"
            )
        await notify.notify_all(
            emails=emails,
            discord_msg=(
                f"📚 **{season.name}** — All books are in! "
                f"Time to rank your favorites. Head to the site and submit your ranking."
                f"{deadline_note}"
            ),
            email_subject=f"{season.name} — Time to rank!",
            email_body=(
                f"<h2>All books are in for {season.name}!</h2>"
                f"<p>Time to rank your favorites. The book with the most Borda points "
                f"gets the top bracket seed.</p>"
                f"{deadline_html}"
                f'<p><a href="{url}/ranking">Submit your ranking →</a></p>'
            ),
        )
        return True
    return False


async def maybe_advance_from_ranking(
    db: AsyncSession, season: Season, *, force: bool = False
) -> bool:
    """Advance ranking → bracket when every participant has ranked (or forced).

    Also computes Borda seeds and creates the first-round bracket matchups.
    """
    if season.state != SeasonState.ranking:
        return False

    total_participants = await crud.count_participants(db, season.id)
    voters = await crud.count_borda_voters(db, season.id)

    if force or (total_participants > 0 and voters >= total_participants):
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
        bracket_deadline_note = ""
        bracket_deadline_html = ""
        if season.bracket_round_hours:
            bracket_deadline_note = (
                f" Each round closes {season.bracket_round_hours}h after the first vote is cast — "
                f"vote early so you're not left out."
            )
            bracket_deadline_html = (
                f"<p><strong>Round deadline:</strong> Each round closes "
                f"{season.bracket_round_hours} hours after the first vote. "
                f"If you don't vote before the round closes, your vote won't count — "
                f"but if everyone votes early we move on straight away.</p>"
            )
        await notify.notify_all(
            emails=emails,
            discord_msg=(
                f"🏆 **{season.name}** — Rankings are locked in! "
                f"The tournament bracket is live. Cast your first-round votes!"
                f"{bracket_deadline_note}"
            ),
            email_subject=f"{season.name} — The bracket is live!",
            email_body=(
                f"<h2>The tournament bracket for {season.name} is live!</h2>"
                f"<p>Rankings are locked in and seeds have been assigned. "
                f"Time to cast your first-round votes.</p>"
                f"{bracket_deadline_html}"
                f'<p><a href="{url}/bracket">Vote now →</a></p>'
            ),
        )
        return True
    return False


async def maybe_advance_bracket_round(
    db: AsyncSession, season: Season, *, force: bool = False
) -> bool:
    """Resolve the current bracket round if all participants have voted on real matchups.

    Byes (book_a == book_b) are already pre-resolved and don't require votes.
    When only 1 unique winner remains after resolving a round, the season is complete.
    When force=True, resolves based on votes cast so far (deadline expiry).
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
        if not force and (total_participants == 0 or voters_done < total_participants):
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
        round_deadline_note = ""
        round_deadline_html = ""
        if season.bracket_round_hours:
            round_deadline_note = (
                f" Round closes {season.bracket_round_hours}h after the first vote — "
                f"vote early so you're not left out."
            )
            round_deadline_html = (
                f"<p><strong>Heads up:</strong> This round closes "
                f"{season.bracket_round_hours} hours after the first vote is cast. "
                f"If you don't vote in time your vote won't count — "
                f"but if everyone votes early we move on straight away.</p>"
            )
        await notify.notify_all(
            emails=emails,
            discord_msg=(
                f"⚔️ **{season.name}** — Round {current_round} is decided! "
                f"The next round is now open for voting.{round_deadline_note}"
            ),
            email_subject=f"{season.name} — Next round is live!",
            email_body=(
                f"<h2>Round {current_round} is decided!</h2>"
                f"<p>The next round of the {season.name} bracket is now open. "
                f"Cast your votes!</p>"
                f"{round_deadline_html}"
                f'<p><a href="{url}/bracket">Vote now →</a></p>'
            ),
        )

    return True


async def _get_bracket_round_deadline(db: AsyncSession, season: Season) -> datetime | None:
    """Compute the deadline for the current bracket round, if bracket_round_hours is set."""
    if not season.bracket_round_hours:
        return None
    current_round = await crud.get_current_bracket_round(db, season.id)
    if current_round == 0:
        return None
    matchups = await crud.get_matchups_for_round(db, season.id, current_round)
    if not matchups:
        return None
    # Use the earliest vote timestamp in this round, or fall back to now + hours
    from sqlalchemy import select as sa_select

    from app.models import BracketVote

    result = await db.execute(
        sa_select(BracketVote.voted_at)
        .where(BracketVote.matchup_id.in_([m.id for m in matchups]))
        .order_by(BracketVote.voted_at.asc())
        .limit(1)
    )
    first_vote = result.scalar_one_or_none()
    if first_vote:
        return first_vote + timedelta(hours=season.bracket_round_hours)
    # No votes yet — deadline starts from now
    return datetime.utcnow() + timedelta(hours=season.bracket_round_hours)


async def get_current_deadline(db: AsyncSession, season: Season) -> datetime | None:
    """Return the active deadline for the season's current phase, or None."""
    if season.state == SeasonState.submit:
        return season.submit_deadline
    if season.state == SeasonState.ranking:
        return season.ranking_deadline
    if season.state == SeasonState.bracket:
        return await _get_bracket_round_deadline(db, season)
    return None


async def check_24h_reminders(db: AsyncSession, season: Season) -> None:
    """Fire a 24-hour reminder for the active phase deadline if not yet sent."""
    now = datetime.utcnow()
    window = timedelta(hours=24)
    url = settings.app_base_url

    if season.state == SeasonState.submit and season.submit_deadline:
        deadline = season.submit_deadline
        if timedelta(0) < deadline - now <= window and not season.submit_reminder_sent:
            stragglers = await crud.users_who_havent_submitted(db, season.id)
            emails = [u.email for u in stragglers if u.email and u.email_notifications]
            await notify.send_deadline_reminder(
                emails,
                season.name,
                "Book submission",
                deadline.strftime("%a %b %d at %H:%M UTC"),
                url,
            )
            season.submit_reminder_sent = True
            await db.commit()

    elif season.state == SeasonState.ranking and season.ranking_deadline:
        deadline = season.ranking_deadline
        if timedelta(0) < deadline - now <= window and not season.ranking_reminder_sent:
            stragglers = await crud.users_who_havent_ranked(db, season.id)
            emails = [u.email for u in stragglers if u.email and u.email_notifications]
            await notify.send_deadline_reminder(
                emails,
                season.name,
                "Book ranking",
                deadline.strftime("%a %b %d at %H:%M UTC"),
                url,
            )
            season.ranking_reminder_sent = True
            await db.commit()

    elif season.state == SeasonState.bracket and season.bracket_round_hours:
        deadline = await _get_bracket_round_deadline(db, season)
        current_round = await crud.get_current_bracket_round(db, season.id)
        if deadline and current_round and timedelta(0) < deadline - now <= window:
            if season.bracket_reminder_round != current_round:
                stragglers = await crud.users_who_havent_voted_round(db, season.id, current_round)
                emails = [u.email for u in stragglers if u.email and u.email_notifications]
                await notify.send_deadline_reminder(
                    emails,
                    season.name,
                    "Bracket round voting",
                    deadline.strftime("%a %b %d at %H:%M UTC"),
                    url,
                )
                season.bracket_reminder_round = current_round
                await db.commit()


async def check_meetup_24h_reminder(db: AsyncSession, meetup: "Meetup") -> None:  # noqa: F821
    """Fire a 24-hour reminder before the meetup poll closes."""
    now = datetime.utcnow()
    window = timedelta(hours=24)
    if not (timedelta(0) < meetup.deadline - now <= window) or meetup.reminder_sent:
        return
    from sqlalchemy import select as sa_select

    from app.models import MeetupOption, MeetupVote

    participants = await crud.get_participants_for_season(db, meetup.season_id)
    result = await db.execute(
        sa_select(MeetupVote.user_id)
        .join(MeetupOption, MeetupVote.option_id == MeetupOption.id)
        .where(MeetupOption.meetup_id == meetup.id)
    )
    voted_ids = set(result.scalars().all())
    emails = [
        u.email for u in participants if u.id not in voted_ids and u.email and u.email_notifications
    ]
    season = await crud.get_season_by_id(db, meetup.season_id)
    season_name = season.name if season else "Meetup poll"
    await notify.send_deadline_reminder(
        emails,
        season_name,
        "Meetup voting",
        meetup.deadline.strftime("%a %b %d at %H:%M UTC"),
        settings.app_base_url,
    )
    meetup.reminder_sent = True
    await db.commit()


async def check_deadline_and_advance(db: AsyncSession, season: Season) -> bool:
    """If the current phase deadline has passed, force-advance the season."""
    now = datetime.utcnow()

    if season.state == SeasonState.submit and season.submit_deadline:
        if now >= season.submit_deadline:
            return await maybe_advance_from_submit(db, season, force=True)

    if season.state == SeasonState.ranking and season.ranking_deadline:
        if now >= season.ranking_deadline:
            return await maybe_advance_from_ranking(db, season, force=True)

    if season.state == SeasonState.bracket and season.bracket_round_hours:
        deadline = await _get_bracket_round_deadline(db, season)
        if deadline and now >= deadline:
            # Resolve based on votes cast so far — no random filler votes
            return await maybe_advance_bracket_round(db, season, force=True)

    return False
