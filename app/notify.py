"""Fire-and-forget Discord and email notifications."""

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

SITE_NAME = "Stumbling Book Club"


def _discord_footer() -> str:
    """A named link to the club, as a Discord masked link.

    Masked rather than a bare URL so a dozen notifications a season don't each
    drag a link preview into the channel behind them.
    """
    return f"\n\n[{SITE_NAME}]({settings.site_url})"


def _email_footer() -> str:
    """A named link to the club, in the app's own forest palette.

    Inline styles only, and a table-free single paragraph — Gmail and Outlook
    strip <style> blocks, so anything set in a stylesheet would arrive bare.
    """
    return (
        '<p style="margin:28px 0 0;padding-top:14px;border-top:1px solid #d9f0d4;'
        'font-family:Georgia,serif;font-size:13px;color:#3d6b36;">'
        f'<a href="{settings.site_url}" style="color:#3d6b36;">{SITE_NAME}</a>'
        "</p>"
    )


async def send_discord(message: str) -> None:
    """Post a message to the configured Discord webhook. Fails silently.

    The club link is appended here rather than by each caller so that every
    message carries one — there are a dozen call sites across state.py and
    main.py, and any new one gets it for free.
    """
    url = settings.discord_webhook_url
    if not url:
        return
    try:
        async with httpx.AsyncClient() as client:
            await client.post(url, json={"content": message + _discord_footer()}, timeout=5)
    except Exception:
        logger.warning("Discord webhook failed", exc_info=True)


async def send_email(to_emails: list[str], subject: str, body: str) -> None:
    """Send one email per recipient via Resend. Fails silently per address.

    Appends the club link for the same reason send_discord does: it belongs on
    every email, and centralising it here is the only way to guarantee that.
    """
    api_key = settings.resend_api_key
    if not api_key or not to_emails:
        return
    body = body + _email_footer()
    async with httpx.AsyncClient() as client:
        for email in to_emails:
            try:
                await client.post(
                    "https://api.resend.com/emails",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "from": f"Stumbling Book Club <{settings.resend_from_email}>",
                        "to": [email],
                        "subject": subject,
                        "html": body,
                    },
                    timeout=10,
                )
            except Exception:
                logger.warning("Resend email to %s failed", email, exc_info=True)


async def notify_all(
    emails: list[str], discord_msg: str, email_subject: str, email_body: str
) -> None:
    """Send both Discord and email notifications."""
    if not settings.notifications_enabled:
        logger.info("Notifications disabled — skipping: %s", discord_msg[:80])
        return
    await send_discord(discord_msg)
    await send_email(emails, email_subject, email_body)


async def send_deadline_reminder(
    emails: list[str],
    season_name: str,
    phase: str,
    deadline_str: str,
    app_url: str,
) -> None:
    """Send a 24-hour deadline reminder to members who still need to act."""
    discord_msg = (
        f"⏰ **{season_name}** — {phase} closes in ~24 hours ({deadline_str}). "
        f"If you haven't yet, head to the site now!"
    )
    email_subject = f"{season_name} — {phase} closes in 24 hours"
    email_body = (
        f"<h2>24-hour reminder</h2>"
        f"<p><strong>{phase}</strong> for {season_name} closes at {deadline_str}.</p>"
        f"<p>If you haven't acted yet, now's the time.</p>"
        f'<p><a href="{app_url}">Head to the site →</a></p>'
    )
    await notify_all(emails, discord_msg, email_subject, email_body)


async def send_urgent_reminder(
    emails: list[str],
    season_name: str,
    phase: str,
    deadline_str: str,
    app_url: str,
) -> None:
    """Send a 1-hour urgent reminder to members who still need to act."""
    discord_msg = (
        f"🚨 **{season_name}** — {phase} closes in **~1 hour** ({deadline_str}). "
        f"Act now or you'll miss it!"
    )
    email_subject = f"⚠️ {season_name} — {phase} closes in 1 hour!"
    email_body = (
        f"<h2>One hour left!</h2>"
        f"<p><strong>{phase}</strong> for {season_name} closes at {deadline_str}.</p>"
        f"<p><strong>You need to act now — there's less than an hour left.</strong></p>"
        f'<p><a href="{app_url}" style="background:#2d6a4f;color:white;padding:10px 20px;'
        f'border-radius:6px;text-decoration:none;font-weight:bold;">Go now →</a></p>'
    )
    await notify_all(emails, discord_msg, email_subject, email_body)


async def send_nudge(
    straggler_names: list[str],
    straggler_emails: list[str],
    season_name: str,
    phase: str,
    app_url: str,
) -> None:
    """Send reminder notifications to stragglers for the current phase."""
    if not straggler_names:
        return
    names_str = ", ".join(straggler_names)
    discord_msg = (
        f"⏰ **{season_name}** — Waiting on {names_str} to {phase}. " f"Don't hold up the club!"
    )
    email_subject = f"{season_name} — Reminder to {phase}"
    email_body = (
        f"<h2>Hey, we're waiting on you!</h2>"
        f"<p>The club is waiting for you to <strong>{phase}</strong> "
        f"for {season_name}.</p>"
        f'<p><a href="{app_url}">Head to the site →</a></p>'
    )
    await notify_all(straggler_emails, discord_msg, email_subject, email_body)
