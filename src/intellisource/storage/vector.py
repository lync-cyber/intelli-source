"""Vector storage and hybrid search (T-005).

Provides VectorStore for pgvector-based embedding storage/retrieval
and HybridIndex for keyword/semantic/hybrid search modes.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Sequence

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# ---------------------------------------------------------------------------
# Shared SQL fragments
# ---------------------------------------------------------------------------

_SEMANTIC_SQL: str = (
    "SELECT id, 1 - (embedding <=> :query) AS score "
    "FROM processed_contents "
    "ORDER BY score DESC LIMIT :top_k"
)

_CLUSTER_SIMILARITY_SQL: str = (
    "SELECT id, 1 - (centroid <=> :query) AS score "
    "FROM content_clusters "
    "ORDER BY score DESC LIMIT :top_k"
)

_KEYWORD_SQL: str = (
    "SELECT id, ts_rank(to_tsvector('simple', body_text), "
    "to_tsquery('simple', :query)) AS score "
    "FROM processed_contents "
    "ORDER BY score DESC LIMIT :top_k"
)

_HYBRID_SQL: str = (
    "SELECT id, "
    "(0.5 * (1 - (embedding <=> :query_vector)) + "
    "0.5 * ts_rank(to_tsvector('simple', body_text), "
    "to_tsquery('simple', :query))) AS score "
    "FROM processed_contents "
    "ORDER BY score DESC LIMIT :top_k"
)

SearchMode = Literal["keyword", "semantic", "hybrid"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rows_to_results(rows: Sequence[Any]) -> list[SearchResult]:
    """Convert raw DB rows (id, score) to a list of SearchResult."""
    return [SearchResult(content_id=row[0], score=float(row[1])) for row in rows]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SearchResult:
    """A single search result with content ID and similarity score."""

    content_id: uuid.UUID
    score: float


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
        result = await self._session.execute(
            text(_SEMANTIC_SQL), {"query": str(query_vector), "top_k": top_k}
        )
        return _rows_to_results(result.all())

    async def search_similar(
        self,
        query_vector: list[float],
        threshold: float,
        top_k: int = 10,
    ) -> list[SearchResult]:
        """Return results with cosine similarity score >= threshold."""
        result = await self._session.execute(
            text(_SEMANTIC_SQL), {"query": str(query_vector), "top_k": top_k}
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
        **kwargs: Any,
    ) -> list[SearchResult]:
        """Search using keyword, semantic, or hybrid mode."""
        if mode == "semantic":
            if query_vector is None:
                raise ValueError("query_vector is required for semantic mode")
            return await self._semantic_search(query_vector, top_k)
        if mode == "keyword":
            if query is None:
                raise ValueError("query is required for keyword mode")
            return await self._keyword_search(query, top_k)
        if mode == "hybrid":
            if query is None:
                raise ValueError("query is required for hybrid mode")
            if query_vector is None:
                raise ValueError("query_vector is required for hybrid mode")
            return await self._hybrid_search(query, query_vector, top_k)
        raise ValueError(f"Invalid search mode: {mode!r}")

    async def _semantic_search(
        self, query_vector: list[float], top_k: int
    ) -> list[SearchResult]:
        result = await self._session.execute(
            text(_SEMANTIC_SQL), {"query": str(query_vector), "top_k": top_k}
        )
        return _rows_to_results(result.all())

    async def _keyword_search(self, query: str, top_k: int) -> list[SearchResult]:
        result = await self._session.execute(
            text(_KEYWORD_SQL), {"query": query, "top_k": top_k}
        )
        return _rows_to_results(result.all())

    async def _hybrid_search(
        self, query: str, query_vector: list[float], top_k: int
    ) -> list[SearchResult]:
        result = await self._session.execute(
            text(_HYBRID_SQL),
            {"query_vector": str(query_vector), "query": query, "top_k": top_k},
        )
        return _rows_to_results(result.all())
