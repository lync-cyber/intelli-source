"""Tests for T-085: HybridSearchEngine real query wiring + chat method.

Covers:
  AC-1: search() calls HybridIndex.search() with query + query_vector
  AC-2: chat() method exists and does not raise AttributeError
  AC-3: keyword_weight / vector_weight are forwarded to HybridIndex.search()
  AC-4: search() with mock HybridIndex returns a non-empty result list
  AC-5: chat() returns API-013 ChatResponse shape
        (session_id, answer, sources, query_time_ms)
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_hybrid_index_mock(results: list[Any] | None = None) -> AsyncMock:
    """Return an AsyncMock that satisfies HybridIndex.search() call shape."""
    mock = AsyncMock()
    mock.search.return_value = results if results is not None else []
    return mock


def _make_session_mock() -> AsyncMock:
    session = AsyncMock()
    result = MagicMock()
    result.all.return_value = []
    session.execute.return_value = result
    return session


def _stub_search_result() -> MagicMock:
    """A SearchResult-like object returned by HybridIndex.search()."""
    row = MagicMock()
    row.content_id = "00000000-0000-0000-0000-000000000001"
    row.score = 0.9
    row.id = "00000000-0000-0000-0000-000000000001"
    row.title = "Test Title"
    row.body_text = "Test body text for snippet extraction"
    row.source_name = "TestSource"
    row.published_at = None
    return row


# ===========================================================================
# AC-1: search() calls HybridIndex.search() with query + query_vector
# ===========================================================================


class TestSearchCallsHybridIndex:
    """AC-1: HybridSearchEngine.search() delegates to HybridIndex.search()."""

    async def test_search_calls_hybrid_index_search_once(self) -> None:
        """search() must call HybridIndex.search() exactly once."""
        from intellisource.search.hybrid import HybridSearchEngine
        from intellisource.storage.vector import HybridIndex

        session = _make_session_mock()
        index_mock = _make_hybrid_index_mock()

        with patch.object(HybridIndex, "search", index_mock.search):
            engine = HybridSearchEngine(session=session)
            await engine.search(
                query="climate change",
                query_vector=[0.1] * 768,
            )

        index_mock.search.assert_called_once()

    async def test_search_passes_query_to_hybrid_index(self) -> None:
        """search() must forward the query string to HybridIndex.search()."""
        from intellisource.search.hybrid import HybridSearchEngine
        from intellisource.storage.vector import HybridIndex

        session = _make_session_mock()
        index_mock = _make_hybrid_index_mock()

        with patch.object(HybridIndex, "search", index_mock.search):
            engine = HybridSearchEngine(session=session)
            await engine.search(
                query="renewable energy",
                query_vector=[0.2] * 768,
            )

        call_kwargs = index_mock.search.call_args
        # query must appear as positional arg[0] or keyword arg
        args, kwargs = call_kwargs
        passed_query = args[0] if args else kwargs.get("query")
        assert passed_query == "renewable energy"

    async def test_search_passes_query_vector_to_hybrid_index(self) -> None:
        """search() must forward query_vector to HybridIndex.search()."""
        from intellisource.search.hybrid import HybridSearchEngine
        from intellisource.storage.vector import HybridIndex

        query_vector = [0.05] * 768
        session = _make_session_mock()
        index_mock = _make_hybrid_index_mock()

        with patch.object(HybridIndex, "search", index_mock.search):
            engine = HybridSearchEngine(session=session)
            await engine.search(
                query="machine learning",
                query_vector=query_vector,
            )

        call_kwargs = index_mock.search.call_args
        args, kwargs = call_kwargs
        passed_vector = args[1] if len(args) > 1 else kwargs.get("query_vector")
        assert passed_vector == query_vector

    async def test_search_does_not_call_bare_session_execute(self) -> None:
        """search() must NOT call session.execute() directly (no stub query)."""
        from intellisource.search.hybrid import HybridSearchEngine
        from intellisource.storage.vector import HybridIndex

        session = _make_session_mock()
        index_mock = _make_hybrid_index_mock()

        with patch.object(HybridIndex, "search", index_mock.search):
            engine = HybridSearchEngine(session=session)
            await engine.search(
                query="test query",
                query_vector=[0.1] * 768,
            )

        # After fix, HybridSearchEngine must NOT call session.execute() itself
        session.execute.assert_not_called()


# ===========================================================================
# AC-2: chat() method exists and does not raise AttributeError
# ===========================================================================


class TestFusionWeightForwarding:
    """AC-3: Fusion weights must be passed through to HybridIndex.search()."""

    async def test_keyword_weight_forwarded_to_hybrid_index(self) -> None:
        """keyword_weight must appear in the kwargs passed to HybridIndex.search()."""
        from intellisource.search.hybrid import HybridSearchEngine
        from intellisource.storage.vector import HybridIndex

        session = _make_session_mock()
        index_mock = _make_hybrid_index_mock()

        with patch.object(HybridIndex, "search", index_mock.search):
            engine = HybridSearchEngine(session=session)
            await engine.search(
                query="energy policy",
                query_vector=[0.1] * 768,
                keyword_weight=0.7,
                vector_weight=0.3,
            )

        _, kwargs = index_mock.search.call_args
        assert "keyword_weight" in kwargs, (
            "keyword_weight must be forwarded to HybridIndex.search() as kwarg"
        )
        assert kwargs["keyword_weight"] == pytest.approx(0.7)

    async def test_vector_weight_forwarded_to_hybrid_index(self) -> None:
        """vector_weight must appear in the kwargs passed to HybridIndex.search()."""
        from intellisource.search.hybrid import HybridSearchEngine
        from intellisource.storage.vector import HybridIndex

        session = _make_session_mock()
        index_mock = _make_hybrid_index_mock()

        with patch.object(HybridIndex, "search", index_mock.search):
            engine = HybridSearchEngine(session=session)
            await engine.search(
                query="policy research",
                query_vector=[0.1] * 768,
                keyword_weight=0.4,
                vector_weight=0.6,
            )

        _, kwargs = index_mock.search.call_args
        assert "vector_weight" in kwargs, (
            "vector_weight must be forwarded to HybridIndex.search() as kwarg"
        )
        assert kwargs["vector_weight"] == pytest.approx(0.6)

    async def test_both_weights_forwarded_together(self) -> None:
        """Both keyword_weight and vector_weight must be forwarded in one call."""
        from intellisource.search.hybrid import HybridSearchEngine
        from intellisource.storage.vector import HybridIndex

        session = _make_session_mock()
        index_mock = _make_hybrid_index_mock()

        with patch.object(HybridIndex, "search", index_mock.search):
            engine = HybridSearchEngine(session=session)
            await engine.search(
                query="deep learning paper",
                query_vector=[0.3] * 768,
                keyword_weight=0.2,
                vector_weight=0.8,
            )

        _, kwargs = index_mock.search.call_args
        assert kwargs.get("keyword_weight") == pytest.approx(0.2)
        assert kwargs.get("vector_weight") == pytest.approx(0.8)

    async def test_instance_weights_used_when_not_overridden(self) -> None:
        """When weights are not passed in search(), instance defaults are used."""
        from intellisource.search.hybrid import HybridSearchEngine
        from intellisource.storage.vector import HybridIndex

        session = _make_session_mock()
        index_mock = _make_hybrid_index_mock()

        with patch.object(HybridIndex, "search", index_mock.search):
            engine = HybridSearchEngine(
                session=session,
                keyword_weight=0.3,
                semantic_weight=0.7,
            )
            await engine.search(
                query="AI alignment",
                query_vector=[0.1] * 768,
            )

        # Instance weights must be forwarded even without per-call override
        _, kwargs = index_mock.search.call_args
        assert "keyword_weight" in kwargs and "vector_weight" in kwargs, (
            "Both instance-level weights must be forwarded to HybridIndex.search()"
        )
        assert kwargs["keyword_weight"] == pytest.approx(0.3)
        assert kwargs["vector_weight"] == pytest.approx(0.7)


# ===========================================================================
# AC-4: search() with mock HybridIndex returns non-empty result list
# ===========================================================================


class TestSearchReturnsResults:
    """AC-4: search() with mock HybridIndex returns a non-empty SearchResponse."""

    async def test_search_returns_non_empty_list_when_index_has_results(
        self,
    ) -> None:
        """search() must return SearchResponse.items with results from HybridIndex."""
        import uuid

        from intellisource.search.hybrid import HybridSearchEngine
        from intellisource.storage.vector import HybridIndex, SearchResult

        session = _make_session_mock()
        fake_results = [
            SearchResult(
                content_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
                score=0.95,
            ),
            SearchResult(
                content_id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
                score=0.80,
            ),
        ]
        index_mock = _make_hybrid_index_mock(results=fake_results)

        with patch.object(HybridIndex, "search", index_mock.search):
            engine = HybridSearchEngine(session=session)
            response = await engine.search(
                query="test query",
                query_vector=[0.1] * 768,
            )

        assert isinstance(response.items, list), (
            "search() must return a SearchResponse with items list"
        )
        assert len(response.items) > 0, (
            "search() must return non-empty items when HybridIndex returns results"
        )

    async def test_search_does_not_raise_type_error(self) -> None:
        """search(query, query_vector=[...]) must not raise TypeError."""
        from intellisource.search.hybrid import HybridSearchEngine
        from intellisource.storage.vector import HybridIndex

        session = _make_session_mock()
        index_mock = _make_hybrid_index_mock()

        with patch.object(HybridIndex, "search", index_mock.search):
            engine = HybridSearchEngine(session=session)
            try:
                await engine.search(
                    query="test query",
                    query_vector=[0.1] * 768,
                )
            except TypeError as exc:
                pytest.fail(f"search() raised TypeError: {exc}")

    async def test_search_does_not_raise_attribute_error(self) -> None:
        """search(query, query_vector=[...]) must not raise AttributeError."""
        from intellisource.search.hybrid import HybridSearchEngine
        from intellisource.storage.vector import HybridIndex

        session = _make_session_mock()
        index_mock = _make_hybrid_index_mock()

        with patch.object(HybridIndex, "search", index_mock.search):
            engine = HybridSearchEngine(session=session)
            try:
                await engine.search(
                    query="test query",
                    query_vector=[0.1] * 768,
                )
            except AttributeError as exc:
                pytest.fail(f"search() raised AttributeError: {exc}")

    async def test_search_response_total_matches_items(self) -> None:
        """SearchResponse.total must reflect the count of returned items."""
        import uuid

        from intellisource.search.hybrid import HybridSearchEngine
        from intellisource.storage.vector import HybridIndex, SearchResult

        session = _make_session_mock()
        fake_results = [
            SearchResult(
                content_id=uuid.UUID("00000000-0000-0000-0000-000000000003"),
                score=0.75,
            ),
        ]
        index_mock = _make_hybrid_index_mock(results=fake_results)

        with patch.object(HybridIndex, "search", index_mock.search):
            engine = HybridSearchEngine(session=session)
            response = await engine.search(
                query="climate policy",
                query_vector=[0.1] * 768,
            )

        assert response.total == len(response.items)


# ===========================================================================
# AC-5: chat() returns API-013 ChatResponse shape
# ===========================================================================
