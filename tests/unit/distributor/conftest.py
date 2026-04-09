"""Shared fixtures for distributor tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture(autouse=True)
def _fast_retry_sleep():
    """Patch asyncio.sleep in distributor channel modules to avoid
    real delays during retry tests."""
    with (
        patch(
            "intellisource.distributor.channels.email.asyncio.sleep",
            new_callable=AsyncMock,
        ),
        patch(
            "intellisource.distributor.channels.wework.asyncio.sleep",
            new_callable=AsyncMock,
        ),
    ):
        yield
