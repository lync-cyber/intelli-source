"""Tests for DATABASE_URL environment variable support in DatabaseManager.

Covers AC-3a, AC-3b, AC-3c.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest


class TestDatabaseManagerUrlResolution:
    """DatabaseManager resolves the connection URL from environment variables."""

    @pytest.mark.asyncio
    async def test_database_url_env_var_used_when_set(self) -> None:
        """AC-3a: DATABASE_URL is used when set."""
        from intellisource.storage.database import DatabaseManager

        test_url = "sqlite+aiosqlite:///:memory:"
        with patch.dict(os.environ, {"DATABASE_URL": test_url}, clear=True):
            manager = DatabaseManager()
            assert str(manager.engine.url) == test_url
            await manager.close()

    @pytest.mark.asyncio
    async def test_sqlite_fallback_when_no_url_and_no_env(self) -> None:
        """AC-3b: sqlite dev fallback used when no URL env vars and ENV is unset."""
        from intellisource.storage.database import DatabaseManager

        with patch.dict(os.environ, {}, clear=True):
            manager = DatabaseManager()
            assert (
                str(manager.engine.url) == "sqlite+aiosqlite:///./intellisource_dev.db"
            )
            await manager.close()

    @pytest.mark.asyncio
    async def test_raises_value_error_in_production_without_database_url(self) -> None:
        """AC-3c: Production + no URL raises ValueError mentioning DATABASE_URL."""
        from intellisource.storage.database import DatabaseManager

        with patch.dict(os.environ, {"ENV": "production"}, clear=True):
            with pytest.raises(ValueError, match="DATABASE_URL"):
                DatabaseManager()
