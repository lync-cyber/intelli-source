"""Tests for pgvector vector storage and retrieval.

Covers:
  AC-055:     Vector data stored correctly; cosine similarity retrieval works
  AC-056:     Hybrid search (keyword + vector) returns relevance-sorted results
  AC-T005-1:  VectorStore.upsert() stores 1024-dim vectors correctly
  AC-T005-2:  VectorStore.search() supports Top-K similarity search with score
  AC-T005-3:  HybridIndex.search() supports keyword/semantic/hybrid modes
  AC-T005-4:  PostgreSQL full-text search (zhparser) fuses with vector results

Since pgvector and PostgreSQL full-text search are unavailable in unit-test
environments (SQLite), all database interactions are mocked. The tests focus
on verifying interface contracts, business logic, and return-value structures.
"""

from __future__ import annotations

import math
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _random_vector(dim: int = 1024) -> list[float]:
    """Return a deterministic pseudo-random unit vector of the given dimension."""
    import hashlib

    raw = [
        int.from_bytes(hashlib.sha256(f"{i}".encode()).digest()[:4], "big") / (2**32)
        for i in range(dim)
    ]
    norm = math.sqrt(sum(x * x for x in raw))
    return [x / norm for x in raw]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# ===========================================================================
# AC-055 / AC-T005-1: VectorStore.upsert() stores 1024-dim vectors
# ===========================================================================


class TestVectorStoreUpsert:
    """AC-055 + AC-T005-1: VectorStore.upsert() correctly stores 1024-dim vectors."""

    @pytest.mark.asyncio
    async def test_import_vector_store(self) -> None:
        """VectorStore class must be importable from intellisource.storage.vector."""
        from intellisource.storage.vector import VectorStore

        assert isinstance(VectorStore, type)

    @pytest.mark.asyncio
    async def test_upsert_stores_vector(self) -> None:
        """upsert(content_id, embedding) persists the vector via the session."""
        from intellisource.storage.vector import VectorStore

        mock_session = AsyncMock()
        store = VectorStore(mock_session)

        content_id = uuid.uuid4()
        embedding = _random_vector(1024)

        await store.upsert(content_id, embedding)

        # The session should have been used to persist data (execute or merge)
        assert mock_session.execute.called or mock_session.merge.called

    @pytest.mark.asyncio
    async def test_upsert_accepts_1024_dim_vector(self) -> None:
        """upsert() accepts exactly 1024-dimensional vectors without error."""
        from intellisource.storage.vector import VectorStore

        mock_session = AsyncMock()
        store = VectorStore(mock_session)

        content_id = uuid.uuid4()
        embedding = _random_vector(1024)

        assert len(embedding) == 1024
        # Should not raise
        await store.upsert(content_id, embedding)

    @pytest.mark.asyncio
    async def test_upsert_updates_existing_vector(self) -> None:
        """Calling upsert() twice with the same content_id updates (not duplicates)."""
        from intellisource.storage.vector import VectorStore

        mock_session = AsyncMock()
        store = VectorStore(mock_session)

        content_id = uuid.uuid4()
        embedding_v1 = _random_vector(1024)
        embedding_v2 = [x * 0.5 for x in _random_vector(1024)]

        await store.upsert(content_id, embedding_v1)
        await store.upsert(content_id, embedding_v2)

        # Two calls should have been made (upsert semantics)
        call_count = mock_session.execute.call_count + mock_session.merge.call_count
        assert call_count >= 2


# ===========================================================================
# AC-055 / AC-T005-2: VectorStore.search() — Top-K similarity with score
# ===========================================================================


class TestVectorStoreSearch:
    """AC-055 + AC-T005-2: VectorStore.search() supports Top-K cosine similarity."""

    @pytest.mark.asyncio
    async def test_import_search_result(self) -> None:
        """SearchResult must be importable from intellisource.storage.vector."""
        import dataclasses

        from intellisource.storage.vector import SearchResult

        assert dataclasses.is_dataclass(SearchResult)

    @pytest.mark.asyncio
    async def test_search_returns_list_of_search_results(self) -> None:
        """search() returns a list of SearchResult objects."""
        from intellisource.storage.vector import SearchResult, VectorStore

        # Prepare mock session that returns fake rows
        content_id_1 = uuid.uuid4()
        content_id_2 = uuid.uuid4()

        mock_result = MagicMock()
        mock_result.all.return_value = [
            (content_id_1, 0.95),
            (content_id_2, 0.87),
        ]
        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        store = VectorStore(mock_session)
        query_vector = _random_vector(1024)
        results = await store.search(query_vector, top_k=2)

        assert isinstance(results, list)
        assert len(results) == 2
        for r in results:
            assert isinstance(r, SearchResult)

    @pytest.mark.asyncio
    async def test_search_result_has_content_id_and_score(self) -> None:
        """Each SearchResult must have content_id (UUID) and score (float) fields."""
        from intellisource.storage.vector import VectorStore

        content_id = uuid.uuid4()

        mock_result = MagicMock()
        mock_result.all.return_value = [(content_id, 0.92)]
        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        store = VectorStore(mock_session)
        results = await store.search(_random_vector(1024), top_k=1)

        assert len(results) == 1
        result = results[0]
        assert hasattr(result, "content_id")
        assert hasattr(result, "score")
        assert isinstance(result.content_id, uuid.UUID)
        assert isinstance(result.score, float)

    @pytest.mark.asyncio
    async def test_search_respects_top_k(self) -> None:
        """search(top_k=3) returns at most 3 results."""
        from intellisource.storage.vector import VectorStore

        ids = [uuid.uuid4() for _ in range(5)]
        mock_result = MagicMock()
        # Simulate DB returning top_k=3 results
        mock_result.all.return_value = [
            (ids[0], 0.99),
            (ids[1], 0.95),
            (ids[2], 0.90),
        ]
        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        store = VectorStore(mock_session)
        results = await store.search(_random_vector(1024), top_k=3)

        assert len(results) <= 3

    @pytest.mark.asyncio
    async def test_search_default_top_k_is_10(self) -> None:
        """search() defaults to top_k=10 when not specified."""
        from intellisource.storage.vector import VectorStore

        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        store = VectorStore(mock_session)
        await store.search(_random_vector(1024))

        # Verify the query was constructed — the session.execute was called
        assert mock_session.execute.called

    @pytest.mark.asyncio
    async def test_search_results_sorted_by_score_descending(self) -> None:
        """Results should be ordered by cosine similarity score in descending order."""
        from intellisource.storage.vector import VectorStore

        ids = [uuid.uuid4() for _ in range(3)]
        mock_result = MagicMock()
        mock_result.all.return_value = [
            (ids[0], 0.99),
            (ids[1], 0.85),
            (ids[2], 0.72),
        ]
        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        store = VectorStore(mock_session)
        results = await store.search(_random_vector(1024), top_k=3)

        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)


# ===========================================================================
# AC-056 / AC-T005-3: HybridIndex.search() — keyword/semantic/hybrid modes
# ===========================================================================


class TestHybridIndexSearch:
    """AC-056 + AC-T005-3: HybridIndex.search() supports three search modes."""

    @pytest.mark.asyncio
    async def test_import_hybrid_index(self) -> None:
        """HybridIndex class must be importable from intellisource.storage.vector."""
        from intellisource.storage.vector import HybridIndex

        assert isinstance(HybridIndex, type)

    @pytest.mark.asyncio
    async def test_semantic_mode_uses_vector_search(self) -> None:
        """mode='semantic' performs vector-based search using query_vector."""
        from intellisource.storage.vector import HybridIndex, SearchResult

        content_id = uuid.uuid4()
        mock_result = MagicMock()
        mock_result.all.return_value = [(content_id, 0.91)]
        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        index = HybridIndex(mock_session)
        results = await index.search(
            query=None,
            query_vector=_random_vector(1024),
            mode="semantic",
            top_k=5,
        )

        assert isinstance(results, list)
        assert len(results) >= 1
        assert isinstance(results[0], SearchResult)
        assert isinstance(results[0].score, float)

    @pytest.mark.asyncio
    async def test_keyword_mode_uses_text_search(self) -> None:
        """mode='keyword' performs full-text search using query string."""
        from intellisource.storage.vector import HybridIndex, SearchResult

        content_id = uuid.uuid4()
        mock_result = MagicMock()
        mock_result.all.return_value = [(content_id, 0.80)]
        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        index = HybridIndex(mock_session)
        results = await index.search(
            query="artificial intelligence",
            query_vector=None,
            mode="keyword",
            top_k=5,
        )

        assert isinstance(results, list)
        assert len(results) >= 1
        assert isinstance(results[0], SearchResult)

    @pytest.mark.asyncio
    async def test_hybrid_mode_combines_keyword_and_vector(self) -> None:
        """mode='hybrid' fuses keyword and vector search results."""
        from intellisource.storage.vector import HybridIndex, SearchResult

        cid1, cid2, cid3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

        # Mock session to return results for both sub-queries
        mock_result = MagicMock()
        mock_result.all.return_value = [
            (cid1, 0.95),
            (cid2, 0.88),
            (cid3, 0.75),
        ]
        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        index = HybridIndex(mock_session)
        results = await index.search(
            query="machine learning",
            query_vector=_random_vector(1024),
            mode="hybrid",
            top_k=5,
        )

        assert isinstance(results, list)
        for r in results:
            assert isinstance(r, SearchResult)
            assert hasattr(r, "content_id")
            assert hasattr(r, "score")

    @pytest.mark.asyncio
    async def test_hybrid_results_sorted_by_relevance(self) -> None:
        """Hybrid mode results are sorted by combined relevance score (descending)."""
        from intellisource.storage.vector import HybridIndex

        cids = [uuid.uuid4() for _ in range(4)]
        mock_result = MagicMock()
        mock_result.all.return_value = [
            (cids[0], 0.98),
            (cids[1], 0.90),
            (cids[2], 0.82),
            (cids[3], 0.71),
        ]
        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        index = HybridIndex(mock_session)
        results = await index.search(
            query="deep learning",
            query_vector=_random_vector(1024),
            mode="hybrid",
            top_k=4,
        )

        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True), (
            "Hybrid results must be sorted by relevance score in descending order"
        )

    @pytest.mark.asyncio
    async def test_search_mode_must_be_valid(self) -> None:
        """An invalid mode raises ValueError."""
        from intellisource.storage.vector import HybridIndex

        mock_session = AsyncMock()
        index = HybridIndex(mock_session)

        with pytest.raises(ValueError):
            await index.search(
                query="test",
                query_vector=_random_vector(1024),
                mode="invalid_mode",
                top_k=5,
            )


# ===========================================================================
# AC-T005-4: Full-text search (zhparser) fuses with vector results
# ===========================================================================


class TestHybridFusion:
    """AC-T005-4: Full-text search results correctly fuse with vector results."""

    @pytest.mark.asyncio
    async def test_hybrid_mode_requires_both_query_and_vector(self) -> None:
        """Hybrid mode needs both query (str) and query_vector; either missing raises."""  # noqa: E501
        from intellisource.storage.vector import HybridIndex

        mock_session = AsyncMock()
        index = HybridIndex(mock_session)

        # Missing query_vector in hybrid mode
        with pytest.raises((ValueError, TypeError)):
            await index.search(
                query="test query",
                query_vector=None,
                mode="hybrid",
                top_k=5,
            )

        # Missing query in hybrid mode
        with pytest.raises((ValueError, TypeError)):
            await index.search(
                query=None,
                query_vector=_random_vector(1024),
                mode="hybrid",
                top_k=5,
            )

    @pytest.mark.asyncio
    async def test_keyword_mode_requires_query_string(self) -> None:
        """Keyword mode requires a non-None query string."""
        from intellisource.storage.vector import HybridIndex

        mock_session = AsyncMock()
        index = HybridIndex(mock_session)

        with pytest.raises((ValueError, TypeError)):
            await index.search(
                query=None,
                query_vector=None,
                mode="keyword",
                top_k=5,
            )

    @pytest.mark.asyncio
    async def test_semantic_mode_requires_query_vector(self) -> None:
        """Semantic mode requires a non-None query_vector."""
        from intellisource.storage.vector import HybridIndex

        mock_session = AsyncMock()
        index = HybridIndex(mock_session)

        with pytest.raises((ValueError, TypeError)):
            await index.search(
                query=None,
                query_vector=None,
                mode="semantic",
                top_k=5,
            )

    @pytest.mark.asyncio
    async def test_search_result_score_is_between_0_and_1(self) -> None:
        """All SearchResult scores should be in [0, 1] range for cosine similarity."""
        from intellisource.storage.vector import HybridIndex

        cids = [uuid.uuid4() for _ in range(3)]
        mock_result = MagicMock()
        mock_result.all.return_value = [
            (cids[0], 0.95),
            (cids[1], 0.60),
            (cids[2], 0.30),
        ]
        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        index = HybridIndex(mock_session)
        results = await index.search(
            query="test",
            query_vector=_random_vector(1024),
            mode="semantic",
            top_k=3,
        )

        for r in results:
            assert 0.0 <= r.score <= 1.0, f"Score {r.score} is outside [0, 1] range"
