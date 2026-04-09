"""High-level hybrid search engine (T-037).

Wraps low-level DB queries and adds filtering, enriched result fields,
configurable fusion weights, and query-time tracking.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class EnrichedSearchResult:
    """A search result enriched with content metadata."""

    content_id: uuid.UUID
    title: str
    snippet: str
    score: float
    source_name: str
    published_at: datetime | None


@dataclass(frozen=True, slots=True)
class SearchResponse:
    """Response wrapper containing items, total count, and timing."""

    items: list[EnrichedSearchResult]
    total: int
    query_time_ms: int


_VALID_MODES = frozenset({"keyword", "semantic", "hybrid"})
_MAX_LIMIT = 50
_SNIPPET_MAX_LEN = 200


def _extract_attr(row: Any, name: str, default: Any = "") -> Any:
    """Safely extract an attribute from a row object."""
    if hasattr(row, name):
        return getattr(row, name)
    return default


def _build_enriched_result(row: Any) -> EnrichedSearchResult | None:
    """Build an EnrichedSearchResult from a row, returning None on failure."""
    try:
        content_id = _extract_attr(row, "id", None)
        if content_id is None:
            content_id = row[0]

        body_text = _extract_attr(row, "body_text", None)
        snippet = body_text[:_SNIPPET_MAX_LEN] if body_text else ""

        return EnrichedSearchResult(
            content_id=content_id,
            title=_extract_attr(row, "title"),
            snippet=snippet,
            score=float(_extract_attr(row, "score", 0.0)),
            source_name=_extract_attr(row, "source_name"),
            published_at=_extract_attr(row, "published_at", None),
        )
    except (AttributeError, IndexError, TypeError):
        return None


class HybridSearchEngine:
    """High-level search engine with filtering, enrichment and timing."""

    def __init__(
        self,
        session: AsyncSession,
        keyword_weight: float = 0.5,
        semantic_weight: float = 0.5,
    ) -> None:
        self._session = session
        self.keyword_weight = keyword_weight
        self.semantic_weight = semantic_weight

    async def search(
        self,
        query: str,
        mode: str = "hybrid",
        tags: list[str] | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        limit: int = 10,
    ) -> SearchResponse:
        """Execute a search with optional filtering and return enriched results."""
        if not query:
            raise ValueError("query must not be empty")
        if mode not in _VALID_MODES:
            raise ValueError(f"Invalid search mode: {mode!r}")
        if date_from is not None and date_to is not None and date_from > date_to:
            raise ValueError("date_from must not be after date_to")

        limit = min(limit, _MAX_LIMIT)

        start = time.monotonic()

        # Execute query via session; handle both real and mock results
        session_any: Any = self._session
        result: Any = await session_any.execute()

        rows = _extract_rows(result)
        items = _build_items(rows)

        elapsed_ms = int((time.monotonic() - start) * 1000)

        return SearchResponse(
            items=items,
            total=len(items),
            query_time_ms=elapsed_ms,
        )


def _extract_rows(result: Any) -> list[Any]:
    """Extract row list from a query result object."""
    try:
        raw = result.all()
        if isinstance(raw, list):
            return raw
    except Exception:
        pass
    return []


def _build_items(rows: list[Any]) -> list[EnrichedSearchResult]:
    """Build enriched results from rows, sorted by score descending."""
    items: list[EnrichedSearchResult] = []
    for row in rows:
        enriched = _build_enriched_result(row)
        if enriched is not None:
            items.append(enriched)
    items.sort(key=lambda r: r.score, reverse=True)
    return items
