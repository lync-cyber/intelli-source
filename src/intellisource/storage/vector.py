"""Vector storage and hybrid search (T-005).

Provides VectorStore for pgvector-based embedding storage/retrieval
and HybridIndex for keyword/semantic/hybrid search modes.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal, Sequence

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# ---------------------------------------------------------------------------
# Shared SQL fragments — column lists are aligned across modes so
# `_rows_to_results` can read the same named columns no matter which mode
# fired the query. Filters (tags / date range) are appended as a WHERE clause
# at query build time; the base SELECT stays as a constant for clarity.
# ---------------------------------------------------------------------------

_SELECT_COLUMNS: str = "id, title, body_text, tags, source_name, published_at"

_SEMANTIC_SQL_TMPL: str = (
    f"SELECT {_SELECT_COLUMNS}, 1 - (embedding <=> :query) AS score "
    "FROM processed_contents {where} "
    "ORDER BY score DESC LIMIT :top_k"
)

_CLUSTER_SIMILARITY_SQL: str = (
    "SELECT id, 1 - (centroid <=> :query) AS score "
    "FROM content_clusters "
    "ORDER BY score DESC LIMIT :top_k"
)

_KEYWORD_SQL_TMPL: str = (
    f"SELECT {_SELECT_COLUMNS}, "
    "ts_rank(to_tsvector('simple', body_text), "
    "to_tsquery('simple', :query)) AS score "
    "FROM processed_contents {where} "
    "ORDER BY score DESC LIMIT :top_k"
)

_HYBRID_SQL_TMPL: str = (
    f"SELECT {_SELECT_COLUMNS}, "
    "(0.5 * (1 - (embedding <=> :query_vector)) + "
    "0.5 * ts_rank(to_tsvector('simple', body_text), "
    "to_tsquery('simple', :query))) AS score "
    "FROM processed_contents {where} "
    "ORDER BY score DESC LIMIT :top_k"
)

SearchMode = Literal["keyword", "semantic", "hybrid"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_where_clause(
    *,
    tags: Sequence[str] | None,
    date_from: datetime | None,
    date_to: datetime | None,
) -> tuple[str, dict[str, Any]]:
    """Compose a parameterised WHERE clause for the optional row filters.

    Returns ``("WHERE foo = :foo AND ...", {"foo": ...})`` or ``("", {})``
    when no filter is requested. JSONB ``tags @> :tags_json`` requires the
    array to be passed as a JSON-encoded string because asyncpg binds
    Python lists as PostgreSQL arrays, not JSONB.
    """
    parts: list[str] = []
    params: dict[str, Any] = {}
    if tags:
        import json

        parts.append("tags @> CAST(:tags_json AS jsonb)")
        params["tags_json"] = json.dumps(list(tags))
    if date_from is not None:
        parts.append("published_at >= :date_from")
        params["date_from"] = date_from
    if date_to is not None:
        parts.append("published_at <= :date_to")
        params["date_to"] = date_to
    if not parts:
        return "", {}
    return "WHERE " + " AND ".join(parts), params


def _rows_to_results(rows: Sequence[Any]) -> list[SearchResult]:
    """Convert raw DB rows to SearchResult, preserving the optional row attrs.

    The mock-based unit tests construct rows as MagicMock with explicit
    ``content_id`` / ``tags`` / ``published_at`` attributes; real
    SQLAlchemy Row objects expose those columns the same way after the
    SELECT list above. Both paths flow through this helper without
    branching.
    """
    out: list[SearchResult] = []
    for row in rows:
        # MagicMock instances respond truthily to any attribute access; tests
        # set ``.content_id`` / ``.tags`` / ``.published_at`` explicitly when
        # they want non-empty values. Real Row objects expose them as columns.
        content_id = getattr(row, "content_id", None)
        if content_id is None:
            content_id = row[0]
        tags = _coerce_tags(getattr(row, "tags", None))
        published_at = _coerce_datetime(getattr(row, "published_at", None))
        out.append(
            SearchResult(
                content_id=content_id,
                score=float(row[1]) if not hasattr(row, "score") else float(row.score),
                tags=tags,
                published_at=published_at,
            )
        )
    return out


def _coerce_tags(value: Any) -> list[str] | None:
    """Return a clean ``list[str]`` if *value* looks like one, else None.

    Guards against MagicMock auto-attributes whose iter/contains are unsafe.
    """
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, tuple):
        return [str(v) for v in value]
    return None


def _coerce_datetime(value: Any) -> datetime | None:
    """Return *value* if it's a real ``datetime``, else None."""
    if isinstance(value, datetime):
        return value
    return None


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SearchResult:
    """A single search result with content ID and similarity score.

    ``tags`` and ``published_at`` are populated when the underlying SQL
    SELECT returned those columns (real ``processed_contents`` row), and
    stay ``None`` for code paths that only know about ``(id, score)``.
    HybridSearchEngine uses them to post-filter results when callers pass
    ``tags`` / ``date_from`` / ``date_to`` without invoking a full SQL
    rebuild.
    """

    content_id: uuid.UUID
    score: float
    tags: list[str] | None = None
    published_at: datetime | None = None


# ---------------------------------------------------------------------------
# VectorStore
# ---------------------------------------------------------------------------


class VectorStore:
    """Stores and retrieves vector embeddings via pgvector."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, content_id: uuid.UUID, embedding: list[float]) -> None:
        """Store or update the embedding for a given content_id."""
        stmt = text(
            "UPDATE processed_contents SET embedding = :embedding WHERE id = :id"
        )
        await self._session.execute(
            stmt, {"embedding": str(embedding), "id": str(content_id)}
        )

    async def search(
        self, query_vector: list[float], top_k: int = 10
    ) -> list[SearchResult]:
        """Return top-K results by cosine similarity."""
        sql = _SEMANTIC_SQL_TMPL.format(where="")
        result = await self._session.execute(
            text(sql), {"query": str(query_vector), "top_k": top_k}
        )
        return _rows_to_results(result.all())

    async def search_similar(
        self,
        query_vector: list[float],
        threshold: float,
        top_k: int = 10,
    ) -> list[SearchResult]:
        """Return results with cosine similarity score >= threshold."""
        sql = _SEMANTIC_SQL_TMPL.format(where="")
        result = await self._session.execute(
            text(sql), {"query": str(query_vector), "top_k": top_k}
        )
        rows = _rows_to_results(result.all())
        return [r for r in rows if r.score >= threshold]

    async def find_nearest_cluster(
        self,
        embedding: list[float],
        threshold: float,
    ) -> dict[str, Any] | None:
        """Return the nearest cluster dict if similarity >= threshold, else None."""
        result = await self._session.execute(
            text(_CLUSTER_SIMILARITY_SQL),
            {"query": str(embedding), "top_k": 1},
        )
        rows = result.all()
        if not rows:
            return None
        row = rows[0]
        score = float(row[1])
        if score < threshold:
            return None
        return {"id": row[0], "score": score}


# ---------------------------------------------------------------------------
# HybridIndex
# ---------------------------------------------------------------------------


class HybridIndex:
    """Hybrid search combining keyword (full-text) and semantic (vector) modes."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def search(
        self,
        query: str | None,
        query_vector: list[float] | None,
        mode: SearchMode,
        top_k: int = 10,
        *,
        tags: Sequence[str] | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        **kwargs: Any,
    ) -> list[SearchResult]:
        """Search using keyword, semantic, or hybrid mode with optional filters.

        ``tags`` / ``date_from`` / ``date_to`` map to ``WHERE`` clauses on the
        ``processed_contents`` table so the filter applies before the
        ``ORDER BY score LIMIT top_k`` cutoff — pushing the predicate up
        front prevents the top-K from being silently shadowed by an
        irrelevant high-score row.
        """
        where_sql, where_params = _build_where_clause(
            tags=tags, date_from=date_from, date_to=date_to
        )
        if mode == "semantic":
            if query_vector is None:
                raise ValueError("query_vector is required for semantic mode")
            return await self._semantic_search(
                query_vector, top_k, where_sql, where_params
            )
        if mode == "keyword":
            if query is None:
                raise ValueError("query is required for keyword mode")
            return await self._keyword_search(query, top_k, where_sql, where_params)
        if mode == "hybrid":
            if query is None:
                raise ValueError("query is required for hybrid mode")
            if query_vector is None:
                raise ValueError("query_vector is required for hybrid mode")
            return await self._hybrid_search(
                query, query_vector, top_k, where_sql, where_params
            )
        raise ValueError(f"Invalid search mode: {mode!r}")

    async def _semantic_search(
        self,
        query_vector: list[float],
        top_k: int,
        where_sql: str = "",
        where_params: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        sql = _SEMANTIC_SQL_TMPL.format(where=where_sql)
        params: dict[str, Any] = {"query": str(query_vector), "top_k": top_k}
        if where_params:
            params.update(where_params)
        result = await self._session.execute(text(sql), params)
        return _rows_to_results(result.all())

    async def _keyword_search(
        self,
        query: str,
        top_k: int,
        where_sql: str = "",
        where_params: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        sql = _KEYWORD_SQL_TMPL.format(where=where_sql)
        params: dict[str, Any] = {"query": query, "top_k": top_k}
        if where_params:
            params.update(where_params)
        result = await self._session.execute(text(sql), params)
        return _rows_to_results(result.all())

    async def _hybrid_search(
        self,
        query: str,
        query_vector: list[float],
        top_k: int,
        where_sql: str = "",
        where_params: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        sql = _HYBRID_SQL_TMPL.format(where=where_sql)
        params: dict[str, Any] = {
            "query_vector": str(query_vector),
            "query": query,
            "top_k": top_k,
        }
        if where_params:
            params.update(where_params)
        result = await self._session.execute(text(sql), params)
        return _rows_to_results(result.all())
