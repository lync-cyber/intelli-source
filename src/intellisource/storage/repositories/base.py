"""BaseRepository -- generic base class for common CRUD and pagination logic."""

from __future__ import annotations

import uuid
from typing import Any, Generic, TypeVar

from sqlalchemy import Select, Text
from sqlalchemy.ext.asyncio import AsyncSession

from intellisource.storage.models import Base

ModelT = TypeVar("ModelT", bound=Base)

# Reusable Text() type for SQLite-compatible LIKE queries on JSON columns.
TEXT_TYPE = Text()

# Maximum items per page (hard cap).
MAX_PAGE_SIZE = 100

# Default items per page when caller omits limit.
DEFAULT_PAGE_SIZE = 20


class PaginatedResult:
    """Typed container for cursor-paginated list results."""

    __slots__ = ("items", "next_cursor", "has_more")

    def __init__(
        self,
        items: list[Any],
        next_cursor: str | None,
        has_more: bool,
    ) -> None:
        self.items = items
        self.next_cursor = next_cursor
        self.has_more = has_more


class BaseRepository(Generic[ModelT]):
    """Shared CRUD helpers for SQLAlchemy-mapped entities.

    Subclasses must set ``_model_class`` to the concrete ORM model.
    """

    _model_class: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # -- create helper -------------------------------------------------------

    async def _create_entity(self, **kwargs: Any) -> ModelT:
        """Instantiate *_model_class*, add to session, flush, and return."""
        entity = self._model_class(**kwargs)
        self._session.add(entity)
        await self._session.flush()
        return entity

    # -- read ----------------------------------------------------------------

    async def get_by_id(self, id: uuid.UUID) -> ModelT | None:  # noqa: A002
        result: ModelT | None = await self._session.get(self._model_class, id)
        return result

    # -- update --------------------------------------------------------------

    async def update(self, id: uuid.UUID, **kwargs: Any) -> ModelT | None:  # noqa: A002
        entity = await self.get_by_id(id)
        if entity is None:
            return None
        for key, value in kwargs.items():
            setattr(entity, key, value)
        await self._session.flush()
        await self._session.refresh(entity)
        return entity

    # -- delete --------------------------------------------------------------

    async def delete(self, id: uuid.UUID) -> bool:  # noqa: A002
        entity = await self.get_by_id(id)
        if entity is None:
            return False
        await self._session.delete(entity)
        await self._session.flush()
        return True

    # -- pagination helper ---------------------------------------------------

    async def _paginate(
        self,
        stmt: Select[tuple[ModelT]],
        *,
        limit: int = DEFAULT_PAGE_SIZE,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """Apply cursor-based pagination to *stmt* and return a page dict.

        The caller is responsible for adding domain-specific WHERE clauses
        **before** calling this helper.  ``_paginate`` appends the cursor
        filter, ORDER BY, and LIMIT, then executes the query.
        """
        limit = min(limit, MAX_PAGE_SIZE)

        if cursor is not None:
            stmt = stmt.where(self._model_class.id > uuid.UUID(cursor))  # type: ignore[attr-defined]

        stmt = stmt.order_by(self._model_class.id).limit(limit + 1)  # type: ignore[attr-defined]
        result = await self._session.execute(stmt)
        rows = list(result.scalars().all())

        has_more = len(rows) > limit
        items = rows[:limit]
        next_cursor = str(items[-1].id) if has_more and items else None  # type: ignore[attr-defined]

        return {"items": items, "next_cursor": next_cursor, "has_more": has_more}
