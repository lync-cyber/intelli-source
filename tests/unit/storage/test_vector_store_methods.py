"""Tests for VectorStore.search_similar and VectorStore.find_nearest_cluster.

Covers T-087 AC-1 and AC-2:
- AC-1: VectorStore.search_similar(query_vector, threshold, top_k) exists and filters
        results whose similarity score < threshold.
- AC-2: VectorStore.find_nearest_cluster(embedding, threshold) exists and returns
        the nearest cluster dict or None when no cluster is above threshold.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# AC-1: VectorStore.search_similar
# ---------------------------------------------------------------------------


class TestVectorStoreSearchSimilar:
    """AC-1: VectorStore.search_similar(query_vector, threshold, top_k)."""

    def test_method_exists_on_vector_store(self) -> None:
        """VectorStore must expose a search_similar method."""
        from intellisource.storage.vector import VectorStore

        session = MagicMock()
        vs = VectorStore(session=session)
        assert hasattr(vs, "search_similar"), (
            "VectorStore must have a 'search_similar' method"
        )
        assert callable(vs.search_similar)

    @pytest.mark.asyncio
    async def test_search_similar_returns_list(self) -> None:
        """search_similar must return a list (possibly empty)."""
        from intellisource.storage.vector import VectorStore

        session = AsyncMock()
        # Simulate DB returning two rows
        row_high = MagicMock()
        row_high.__getitem__ = lambda self, i: [uuid.uuid4(), 0.9][i]
        row_low = MagicMock()
        row_low.__getitem__ = lambda self, i: [uuid.uuid4(), 0.3][i]

        mock_result = MagicMock()
        mock_result.all.return_value = [row_high, row_low]
        session.execute = AsyncMock(return_value=mock_result)

        vs = VectorStore(session=session)
        results = await vs.search_similar(
            query_vector=[0.1, 0.2, 0.3],
            threshold=0.5,
            top_k=5,
        )
        assert isinstance(results, list), "search_similar must return a list"

    @pytest.mark.asyncio
    async def test_search_similar_filters_below_threshold(self) -> None:
        """Results with score < threshold must not appear in the output."""
        from intellisource.storage.vector import VectorStore

        session = AsyncMock()

        # Two candidates: score 0.9 (above threshold 0.7) and 0.3 (below)
        id_high = uuid.uuid4()
        id_low = uuid.uuid4()

        class _Row:
            def __init__(self, cid: uuid.UUID, score: float) -> None:
                self.content_id = cid
                self.score = score
                self._items = [cid, score]

            def __getitem__(self, i: int) -> Any:
                return self._items[i]

        mock_result = MagicMock()
        mock_result.all.return_value = [_Row(id_high, 0.9), _Row(id_low, 0.3)]
        session.execute = AsyncMock(return_value=mock_result)

        vs = VectorStore(session=session)
        results = await vs.search_similar(
            query_vector=[0.1, 0.2, 0.3],
            threshold=0.7,
            top_k=10,
        )

        # Only the high-score result should survive threshold filtering
        scores = [
            (r.score if hasattr(r, "score") else r.get("score", r[1]))
            for r in results
        ]
        assert all(s >= 0.7 for s in scores), (
            f"All returned scores must be >= threshold 0.7, got: {scores}"
        )
        # The low-score entry must be absent
        returned_ids = [
            (r.content_id if hasattr(r, "content_id") else r.get("content_id", r[0]))
            for r in results
        ]
        assert id_low not in returned_ids, (
            "Entry with score 0.3 must be filtered out by threshold 0.7"
        )

    @pytest.mark.asyncio
    async def test_search_similar_empty_when_all_below_threshold(self) -> None:
        """search_similar returns empty list when all candidates are below threshold."""
        from intellisource.storage.vector import VectorStore

        session = AsyncMock()

        class _Row:
            def __init__(self, cid: uuid.UUID, score: float) -> None:
                self.content_id = cid
                self.score = score
                self._items = [cid, score]

            def __getitem__(self, i: int) -> Any:
                return self._items[i]

        mock_result = MagicMock()
        mock_result.all.return_value = [
            _Row(uuid.uuid4(), 0.2),
            _Row(uuid.uuid4(), 0.1),
        ]
        session.execute = AsyncMock(return_value=mock_result)

        vs = VectorStore(session=session)
        results = await vs.search_similar(
            query_vector=[0.1, 0.2, 0.3],
            threshold=0.8,
            top_k=10,
        )
        assert results == [], (
            "Expected empty list when no candidates exceed threshold=0.8"
        )


# ---------------------------------------------------------------------------
# AC-2: VectorStore.find_nearest_cluster
# ---------------------------------------------------------------------------


class TestVectorStoreFindNearestCluster:
    """AC-2: VectorStore.find_nearest_cluster(embedding, threshold) -> dict | None."""

    def test_method_exists_on_vector_store(self) -> None:
        """VectorStore must expose a find_nearest_cluster method."""
        from intellisource.storage.vector import VectorStore

        session = MagicMock()
        vs = VectorStore(session=session)
        assert hasattr(vs, "find_nearest_cluster"), (
            "VectorStore must have a 'find_nearest_cluster' method"
        )
        assert callable(vs.find_nearest_cluster)

    @pytest.mark.asyncio
    async def test_find_nearest_cluster_returns_none_when_no_match(self) -> None:
        """find_nearest_cluster returns None when no cluster is above threshold."""
        from intellisource.storage.vector import VectorStore

        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        session.execute = AsyncMock(return_value=mock_result)

        vs = VectorStore(session=session)
        result = await vs.find_nearest_cluster(
            embedding=[0.1, 0.2, 0.3],
            threshold=0.8,
        )
        assert result is None, (
            "find_nearest_cluster must return None when no cluster matches threshold"
        )

    @pytest.mark.asyncio
    async def test_find_nearest_cluster_returns_cluster_dict_above_threshold(
        self,
    ) -> None:
        """find_nearest_cluster returns a dict with 'id' when a cluster matches."""
        from intellisource.storage.vector import VectorStore

        cluster_id = uuid.uuid4()
        session = AsyncMock()

        class _Row:
            def __init__(self, cid: uuid.UUID, score: float) -> None:
                self.cluster_id = cid
                self.id = cid
                self.score = score
                self._items = [cid, score]

            def __getitem__(self, i: int) -> Any:
                return self._items[i]

        mock_result = MagicMock()
        mock_result.all.return_value = [_Row(cluster_id, 0.85)]
        session.execute = AsyncMock(return_value=mock_result)

        vs = VectorStore(session=session)
        result = await vs.find_nearest_cluster(
            embedding=[0.1, 0.2, 0.3],
            threshold=0.7,
        )
        assert result is not None, (
            "find_nearest_cluster must return a result when a cluster exceeds threshold"
        )
        assert "id" in result or hasattr(result, "id"), (
            "Returned cluster must include an 'id' field"
        )

    @pytest.mark.asyncio
    async def test_find_nearest_cluster_none_when_score_below_threshold(self) -> None:
        """find_nearest_cluster returns None when the best cluster is below threshold."""
        from intellisource.storage.vector import VectorStore

        session = AsyncMock()

        class _Row:
            def __init__(self, cid: uuid.UUID, score: float) -> None:
                self.cluster_id = cid
                self.id = cid
                self.score = score
                self._items = [cid, score]

            def __getitem__(self, i: int) -> Any:
                return self._items[i]

        mock_result = MagicMock()
        mock_result.all.return_value = [_Row(uuid.uuid4(), 0.4)]
        session.execute = AsyncMock(return_value=mock_result)

        vs = VectorStore(session=session)
        result = await vs.find_nearest_cluster(
            embedding=[0.1, 0.2, 0.3],
            threshold=0.7,
        )
        assert result is None, (
            "find_nearest_cluster must return None when best cluster score < threshold"
        )
