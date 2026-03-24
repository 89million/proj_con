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
