"""Fire-and-forget Discord webhook notifications."""

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
