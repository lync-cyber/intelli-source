"""Shared callable aliases for the MCP server wiring."""

from __future__ import annotations

from typing import Any, Callable

from sqlalchemy.ext.asyncio import AsyncSession

# A session factory is a zero-arg callable returning an async context manager
# that yields an AsyncSession (e.g. ``DatabaseManager.get_session``).
SessionFactory = Callable[[], Any]
SearchEngineFactory = Callable[[AsyncSession], Any]
