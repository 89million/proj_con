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
    """Send an email via Resend to a list of recipients. Fails silently."""
    api_key = settings.resend_api_key
    if not api_key or not to_emails:
        return
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "from": f"Stumbling Book Club <{settings.resend_from_email}>",
                    "to": to_emails,
                    "subject": subject,
                    "html": body,
                },
                timeout=10,
            )
    except Exception:
        logger.warning("Resend email failed", exc_info=True)


async def notify_all(
    emails: list[str], discord_msg: str, email_subject: str, email_body: str
) -> None:
    """Send both Discord and email notifications."""
    await send_discord(discord_msg)
    await send_email(emails, email_subject, email_body)
