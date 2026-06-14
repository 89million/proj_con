# Shared test fixtures — imported automatically by pytest

from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture(autouse=True)
def _disable_notifications():
    """Prevent tests from sending real Discord/email notifications."""
    with (
        patch("app.notify.send_discord", new_callable=AsyncMock),
        patch("app.notify.send_email", new_callable=AsyncMock),
    ):
        yield


@pytest.fixture(autouse=True)
def _disable_cover_fetch():
    """Prevent tests from making real OpenLibrary cover lookups on submission."""
    with patch("app.main.fetch_cover_url", new_callable=AsyncMock, return_value=None):
        yield
