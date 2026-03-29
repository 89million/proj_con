"""Fire-and-forget Discord and email notifications."""

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


async def send_discord(message: str) -> None:
    """Post a message to the configured Discord webhook. Fails silently."""
    url = settings.discord_webhook_url
    if not url:
        return
    try:
        async with httpx.AsyncClient() as client:
            await client.post(url, json={"content": message}, timeout=5)
    except Exception:
        logger.warning("Discord webhook failed", exc_info=True)


async def send_email(to_emails: list[str], subject: str, body: str) -> None:
    """Send one email per recipient via Resend. Fails silently per address."""
    api_key = settings.resend_api_key
    if not api_key or not to_emails:
        return
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
