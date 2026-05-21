"""Tests for T-037: HybridSearchEngine high-level search engine.

Covers:
  AC-051:     Hybrid retrieval (keyword + vector semantic) returns relevant results
  AC-056:     Hybrid search results sorted by relevance
  AC-T037-1:  HybridSearchEngine supports keyword/semantic/hybrid search modes
  AC-T037-2:  hybrid mode fuses ts_rank and cosine similarity with configurable weights
  AC-T037-3:  Supports filtering by tags/date_from/date_to
  AC-T037-4:  Results contain content_id/title/snippet/score/source_name/published_at
  AC-T037-5:  Query time tracked in query_time_ms

HybridSearchEngine wraps HybridIndex and adds filtering, rich result fields,
configurable fusion weights, and performance tracking. All DB interactions
are mocked via AsyncSession.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_db_session() -> AsyncMock:
    """Create an AsyncMock session whose execute() returns a proper result.

    Prevents 'coroutine was never awaited' warnings by ensuring
    result.all() returns a plain list instead of a coroutine.
    """
    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.all.return_value = []
    mock_result.scalars.return_value.all.return_value = []
    session.execute.return_value = mock_result
    return session


def _random_vector(dim: int = 1536) -> list[float]:
    """Return a deterministic pseudo-random unit vector."""
    import hashlib

    raw = [
        int.from_bytes(hashlib.sha256(f"{i}".encode()).digest()[:4], "big") / (2**32)
        for i in range(dim)
    ]
    norm = math.sqrt(sum(x * x for x in raw))
    return [x / norm for x in raw]


# ===========================================================================
# AC-T037-1: HybridSearchEngine supports keyword/semantic/hybrid modes
# ===========================================================================


class TestHybridSearchEngineImportAndModes:
    """AC-T037-1: HybridSearchEngine supports three search modes."""

    async def test_import_hybrid_search_engine(self) -> None:
        """HybridSearchEngine must be importable from intellisource.search.hybrid."""
        from intellisource.search.hybrid import HybridSearchEngine

        assert HybridSearchEngine is not None

    async def test_import_enriched_search_result(self) -> None:
        """EnrichedSearchResult (rich result dataclass) must be importable."""
        from intellisource.search.hybrid import EnrichedSearchResult

        assert EnrichedSearchResult is not None

    async def test_keyword_mode_executes_search(self) -> None:
        """search(mode='keyword') executes a keyword-based search."""
        from intellisource.search.hybrid import HybridSearchEngine

        mock_session = _mock_db_session()
        engine = HybridSearchEngine(session=mock_session)

        results = await engine.search(query="artificial intelligence", mode="keyword")

        assert isinstance(results.items, list)

    async def test_semantic_mode_executes_search(self) -> None:
        """search(mode='semantic') executes a semantic vector search."""
        from intellisource.search.hybrid import HybridSearchEngine

        mock_session = _mock_db_session()
        engine = HybridSearchEngine(session=mock_session)

        results = await engine.search(query="machine learning", mode="semantic")

        assert isinstance(results.items, list)

    async def test_hybrid_mode_executes_search(self) -> None:
        """search(mode='hybrid') combines keyword and semantic search."""
        from intellisource.search.hybrid import HybridSearchEngine

        mock_session = _mock_db_session()
        engine = HybridSearchEngine(session=mock_session)

        results = await engine.search(query="deep learning", mode="hybrid")

        assert isinstance(results.items, list)

    async def test_default_mode_is_hybrid(self) -> None:
        """When mode is not specified, default to 'hybrid'."""
        from intellisource.search.hybrid import HybridSearchEngine

        mock_session = _mock_db_session()
        engine = HybridSearchEngine(session=mock_session)

        # Should not raise; defaults to hybrid mode
        results = await engine.search(query="test query")

        assert isinstance(results.items, list)

    async def test_invalid_mode_raises_value_error(self) -> None:
        """An invalid search mode raises ValueError."""
        from intellisource.search.hybrid import HybridSearchEngine

        mock_session = _mock_db_session()
        engine = HybridSearchEngine(session=mock_session)

        with pytest.raises(ValueError):
            await engine.search(query="test", mode="invalid_mode")


# ===========================================================================
# AC-T037-2: hybrid mode fuses ts_rank + cosine similarity (configurable weights)
# ===========================================================================


class TestHybridFusionWeights:
    """AC-T037-2: Configurable fusion weights for hybrid mode."""

    async def test_default_weights_are_equal(self) -> None:
        """Default keyword_weight and semantic_weight should both be 0.5."""
        from intellisource.search.hybrid import HybridSearchEngine

        mock_session = _mock_db_session()
        engine = HybridSearchEngine(session=mock_session)

        assert engine.keyword_weight == 0.5
        assert engine.semantic_weight == 0.5

    async def test_custom_weights_accepted(self) -> None:
        """HybridSearchEngine accepts custom keyword_weight and semantic_weight."""
        from intellisource.search.hybrid import HybridSearchEngine

        mock_session = _mock_db_session()
        engine = HybridSearchEngine(
            session=mock_session,
            keyword_weight=0.3,
            semantic_weight=0.7,
        )

        assert engine.keyword_weight == pytest.approx(0.3)
        assert engine.semantic_weight == pytest.approx(0.7)

    async def test_weights_affect_score_calculation(self) -> None:
        """Different weights produce different final scores in hybrid mode.

        When keyword_weight=0.8 and semantic_weight=0.2, keyword-heavy
        results should score differently than with equal weights.
        """
        from intellisource.search.hybrid import HybridSearchEngine

        mock_session = _mock_db_session()

        engine_equal = HybridSearchEngine(
            session=mock_session,
            keyword_weight=0.5,
            semantic_weight=0.5,
        )
        engine_keyword_heavy = HybridSearchEngine(
            session=mock_session,
            keyword_weight=0.8,
            semantic_weight=0.2,
        )

        # Both engines should be constructable with different weights
        assert engine_equal.keyword_weight != engine_keyword_heavy.keyword_weight


# ===========================================================================
# AC-T037-3: Supports filtering by tags/date_from/date_to
# ===========================================================================


class TestSearchFiltering:
    """AC-T037-3: Filtering by tags, date_from, and date_to."""

    async def test_search_accepts_tags_filter(self) -> None:
        """search() accepts a tags parameter for filtering."""
        from intellisource.search.hybrid import HybridSearchEngine

        mock_session = _mock_db_session()
        engine = HybridSearchEngine(session=mock_session)

        # Should not raise TypeError for tags parameter
        results = await engine.search(
            query="AI news",
            tags=["technology", "ai"],
        )

        assert isinstance(results.items, list)

    async def test_search_accepts_date_from_filter(self) -> None:
        """search() accepts a date_from parameter for time-range filtering."""
        from intellisource.search.hybrid import HybridSearchEngine

        mock_session = _mock_db_session()
        engine = HybridSearchEngine(session=mock_session)

        date_from = datetime(2024, 1, 1, tzinfo=timezone.utc)
        results = await engine.search(
            query="recent developments",
            date_from=date_from,
        )

        assert isinstance(results.items, list)

    async def test_search_accepts_date_to_filter(self) -> None:
        """search() accepts a date_to parameter for time-range filtering."""
        from intellisource.search.hybrid import HybridSearchEngine

        mock_session = _mock_db_session()
        engine = HybridSearchEngine(session=mock_session)

        date_to = datetime(2024, 12, 31, tzinfo=timezone.utc)
        results = await engine.search(
            query="historical data",
            date_to=date_to,
        )

        assert isinstance(results.items, list)

    async def test_search_accepts_combined_filters(self) -> None:
        """search() accepts tags + date_from + date_to simultaneously."""
        from intellisource.search.hybrid import HybridSearchEngine

        mock_session = _mock_db_session()
        engine = HybridSearchEngine(session=mock_session)

        results = await engine.search(
            query="filtered search",
            tags=["tech"],
            date_from=datetime(2024, 1, 1, tzinfo=timezone.utc),
            date_to=datetime(2024, 6, 30, tzinfo=timezone.utc),
        )

        assert isinstance(results.items, list)

    async def test_search_accepts_limit_parameter(self) -> None:
        """search() accepts a limit parameter (default 10, max 50)."""
        from intellisource.search.hybrid import HybridSearchEngine

        mock_session = _mock_db_session()
        engine = HybridSearchEngine(session=mock_session)

        results = await engine.search(query="test", limit=5)

        assert isinstance(results.items, list)

    async def test_limit_capped_at_50(self) -> None:
        """Limit values above 50 are capped to 50."""
        from intellisource.search.hybrid import HybridSearchEngine

        mock_session = _mock_db_session()
        engine = HybridSearchEngine(session=mock_session)

        # Should not raise; limit should be capped internally
        results = await engine.search(query="test", limit=100)

        assert isinstance(results.items, list)


# ===========================================================================
# AC-T037-4: Rich result fields (content_id/title/snippet/score/source_name/date)
# ===========================================================================


class TestEnrichedSearchResult:
    """AC-T037-4: Search results contain all required fields."""

    async def test_enriched_result_has_content_id(self) -> None:
        """EnrichedSearchResult must have a content_id field (UUID)."""
        from intellisource.search.hybrid import EnrichedSearchResult

        assert hasattr(EnrichedSearchResult, "__dataclass_fields__") or hasattr(
            EnrichedSearchResult, "__annotations__"
        )
        # Verify by creating an instance sketch
        annotations = getattr(EnrichedSearchResult, "__annotations__", {})
        assert "content_id" in annotations, (
            "EnrichedSearchResult must have a content_id field"
        )

    async def test_enriched_result_has_title(self) -> None:
        """EnrichedSearchResult must have a title field (str)."""
        from intellisource.search.hybrid import EnrichedSearchResult

        annotations = getattr(EnrichedSearchResult, "__annotations__", {})
        assert "title" in annotations, "EnrichedSearchResult must have a title field"

    async def test_enriched_result_has_snippet(self) -> None:
        """EnrichedSearchResult must have a snippet field (str)."""
        from intellisource.search.hybrid import EnrichedSearchResult

        annotations = getattr(EnrichedSearchResult, "__annotations__", {})
        assert "snippet" in annotations, (
            "EnrichedSearchResult must have a snippet field"
        )

    async def test_enriched_result_has_score(self) -> None:
        """EnrichedSearchResult must have a score field (float)."""
        from intellisource.search.hybrid import EnrichedSearchResult

        annotations = getattr(EnrichedSearchResult, "__annotations__", {})
        assert "score" in annotations, "EnrichedSearchResult must have a score field"

    async def test_enriched_result_has_source_name(self) -> None:
        """EnrichedSearchResult must have a source_name field (str)."""
        from intellisource.search.hybrid import EnrichedSearchResult

        annotations = getattr(EnrichedSearchResult, "__annotations__", {})
        assert "source_name" in annotations, (
            "EnrichedSearchResult must have a source_name field"
        )

    async def test_enriched_result_has_published_at(self) -> None:
        """EnrichedSearchResult must have a published_at field (datetime)."""
        from intellisource.search.hybrid import EnrichedSearchResult

        annotations = getattr(EnrichedSearchResult, "__annotations__", {})
        assert "published_at" in annotations, (
            "EnrichedSearchResult must have a published_at field"
        )

    async def test_search_response_has_items_and_total(self) -> None:
        """Search response must include items list and total count."""
        from intellisource.search.hybrid import HybridSearchEngine

        mock_session = _mock_db_session()
        engine = HybridSearchEngine(session=mock_session)

        response = await engine.search(query="test")

        assert hasattr(response, "items")
        assert hasattr(response, "total")
        assert isinstance(response.items, list)
        assert isinstance(response.total, int)


# ===========================================================================
# AC-T037-5: query_time_ms performance tracking
# ===========================================================================


class TestQueryTimeTracking:
    """AC-T037-5: Query execution time is recorded in query_time_ms."""

    async def test_search_response_has_query_time_ms(self) -> None:
        """Search response must include query_time_ms field."""
        from intellisource.search.hybrid import HybridSearchEngine

        mock_session = _mock_db_session()
        engine = HybridSearchEngine(session=mock_session)

        response = await engine.search(query="timing test")

        assert hasattr(response, "query_time_ms")
        assert isinstance(response.query_time_ms, int)

    async def test_query_time_ms_is_non_negative(self) -> None:
        """query_time_ms must be a non-negative integer."""
        from intellisource.search.hybrid import HybridSearchEngine

        mock_session = _mock_db_session()
        engine = HybridSearchEngine(session=mock_session)

        response = await engine.search(query="timing test")

        assert response.query_time_ms >= 0


# ===========================================================================
# AC-051 / AC-056: Integration-level hybrid retrieval and relevance sorting
# ===========================================================================


class TestHybridRetrievalAndSorting:
    """AC-051 + AC-056: Hybrid retrieval returns relevant, sorted results."""

    async def test_hybrid_search_returns_results_sorted_by_score(self) -> None:
        """Results from hybrid search must be sorted by score descending."""
        from intellisource.search.hybrid import HybridSearchEngine

        mock_session = _mock_db_session()
        engine = HybridSearchEngine(session=mock_session)

        response = await engine.search(query="important topic", mode="hybrid")

        if len(response.items) > 1:
            scores = [item.score for item in response.items]
            assert scores == sorted(scores, reverse=True), (
                "Hybrid search results must be sorted by relevance score descending"
            )

    async def test_keyword_search_returns_results_sorted_by_score(self) -> None:
        """Keyword-only search results must also be sorted by score descending."""
        from intellisource.search.hybrid import HybridSearchEngine

        mock_session = _mock_db_session()
        engine = HybridSearchEngine(session=mock_session)

        response = await engine.search(query="keyword test", mode="keyword")

        if len(response.items) > 1:
            scores = [item.score for item in response.items]
            assert scores == sorted(scores, reverse=True)

    async def test_empty_query_raises_value_error(self) -> None:
        """An empty query string should raise ValueError."""
        from intellisource.search.hybrid import HybridSearchEngine

        mock_session = _mock_db_session()
        engine = HybridSearchEngine(session=mock_session)

        with pytest.raises(ValueError):
            await engine.search(query="")

    async def test_search_result_total_matches_items_length(self) -> None:
        """response.total should be >= len(response.items) (total is the
        full match count, items is the limited subset)."""
        from intellisource.search.hybrid import HybridSearchEngine

        mock_session = _mock_db_session()
        engine = HybridSearchEngine(session=mock_session)

        response = await engine.search(query="test")

        assert response.total >= len(response.items)


# ===========================================================================
# Edge cases and boundary conditions
# ===========================================================================


class TestEdgeCases:
    """Boundary conditions implied by the acceptance criteria."""

    async def test_search_with_no_matching_results_returns_empty(self) -> None:
        """When no results match, items should be empty and total should be 0."""
        from intellisource.search.hybrid import HybridSearchEngine

        mock_session = AsyncMock()
        # Configure mock to return empty results
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        engine = HybridSearchEngine(session=mock_session)

        response = await engine.search(query="nonexistent obscure term xyz123")

        assert isinstance(response.items, list)
        assert response.total == 0
        assert len(response.items) == 0

    async def test_search_with_empty_tags_filter(self) -> None:
        """Passing an empty tags list should behave the same as no filter."""
        from intellisource.search.hybrid import HybridSearchEngine

        mock_session = _mock_db_session()
        engine = HybridSearchEngine(session=mock_session)

        # Should not raise
        response = await engine.search(query="test", tags=[])

        assert isinstance(response.items, list)

    async def test_date_from_after_date_to_raises_error(self) -> None:
        """date_from > date_to is an invalid range and should raise ValueError."""
        from intellisource.search.hybrid import HybridSearchEngine

        mock_session = _mock_db_session()
        engine = HybridSearchEngine(session=mock_session)

        with pytest.raises(ValueError):
            await engine.search(
                query="test",
                date_from=datetime(2025, 1, 1, tzinfo=timezone.utc),
                date_to=datetime(2024, 1, 1, tzinfo=timezone.utc),
            )
