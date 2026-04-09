"""Shared fixtures for scheduler tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture(autouse=True)
def _fast_retry_sleep():
    """Patch asyncio.sleep in the tasks module to avoid real delays
    during retry/backoff tests."""
    with patch(
        "intellisource.scheduler.tasks.asyncio.sleep",
        new_callable=AsyncMock,
    ):
        yield
