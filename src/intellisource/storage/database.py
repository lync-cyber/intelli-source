"""Database connection management and ORM base (T-002).

Provides ``DatabaseManager`` — an async connection pool manager built on
SQLAlchemy 2.0's ``create_async_engine`` and ``async_sessionmaker``.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    create_async_engine,
)
from sqlalchemy.orm import sessionmaker


class DatabaseManager:
    """Manages an async SQLAlchemy engine and session factory.

    Parameters
    ----------
    database_url:
        An async-compatible database URL.  When omitted the value is read
        from the ``IS_DATABASE_URL`` environment variable.  If neither is
        provided a ``ValueError`` is raised.
    """

    def __init__(self, database_url: str | None = None) -> None:
        url = database_url or os.environ.get("IS_DATABASE_URL")
        if not url:
            raise ValueError(
                "database_url must be provided or IS_DATABASE_URL "
                "environment variable must be set"
            )
        self._engine: AsyncEngine = create_async_engine(url)
        self._session_factory = sessionmaker(
            bind=self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        self._closed = False

    @property
    def engine(self) -> AsyncEngine:
        """Return the underlying :class:`AsyncEngine`."""
        return self._engine

    @asynccontextmanager
    async def get_session(self) -> AsyncIterator[AsyncSession]:
        """Yield an ``AsyncSession`` that auto-commits or rolls back."""
        if self._closed:
            raise RuntimeError("DatabaseManager is closed")
        session: AsyncSession = self._session_factory()
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def close(self) -> None:
        """Dispose of the engine and release all pool connections."""
        if not self._closed:
            await self._engine.dispose()

            # Prevent the pool from handing out new connections after dispose.
            # This is necessary because some pool implementations (e.g.
            # StaticPool used by SQLite) silently recreate connections.
            def _closed_creator(*a: object, **kw: object) -> None:
                raise RuntimeError("DatabaseManager is closed")

            self._engine.pool._creator = _closed_creator  # type: ignore[assignment]
            self._closed = True
