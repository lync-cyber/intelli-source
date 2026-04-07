"""Tests for SemanticDedup and FingerprintGenerator.

Covers:
- AC-019: Vector retrieval candidates -> LLM precise duplicate determination
- AC-022: Unique fingerprint per content, idempotent processing across pipeline
- AC-T023-1: Similarity threshold configurable (default 0.85)
- AC-T023-2: Dedup flow: embedding -> vector search -> LLM judge -> mark duplicate
- AC-T023-3: Fallback logic uses content fingerprint + SimHash similarity
- AC-T023-4: FingerprintGenerator produces stable SHA-256 fingerprints (title+body normalized)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from intellisource.llm.processors.dedup import FingerprintGenerator, SemanticDedup

from intellisource.pipeline.base import BaseProcessor
from intellisource.pipeline.context import PipelineContext

# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

SAMPLE_TITLE = "Introduction to Machine Learning"
SAMPLE_BODY = (
    "This paper introduces fundamental concepts of machine learning "
    "including supervised and unsupervised learning."
)

DUPLICATE_TITLE = "Introduction to Machine Learning"
DUPLICATE_BODY = (
    "This paper introduces fundamental concepts of machine learning "
    "including supervised and unsupervised learning."
)

DIFFERENT_TITLE = "Deep Learning in Practice"
DIFFERENT_BODY = "A practical guide to deploying deep learning models in production."


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_gateway() -> AsyncMock:
    """Create a mock LLMGateway for duplicate determination."""
    gateway = AsyncMock()
    result = MagicMock()
    result.content = '{"is_duplicate": true, "confidence": 0.95}'
    result.metadata = {
        "input_tokens": 150,
        "output_tokens": 30,
        "latency_ms": 180.0,
        "model": "gpt-4o-mini",
    }
    gateway.complete = AsyncMock(return_value=result)
    return gateway


@pytest.fixture
def mock_gateway_not_duplicate() -> AsyncMock:
    """LLM gateway that judges content as NOT duplicate."""
    gateway = AsyncMock()
    result = MagicMock()
    result.content = '{"is_duplicate": false, "confidence": 0.30}'
    result.metadata = {
        "input_tokens": 150,
        "output_tokens": 30,
        "latency_ms": 180.0,
        "model": "gpt-4o-mini",
    }
    gateway.complete = AsyncMock(return_value=result)
    return gateway


@pytest.fixture
def mock_vector_store_with_candidates() -> MagicMock:
    """Vector store that returns similar candidates above threshold."""
    store = MagicMock()
    candidate = MagicMock()
    candidate.id = "existing-doc-001"
    candidate.score = 0.92
    candidate.title = SAMPLE_TITLE
    candidate.body_text = SAMPLE_BODY
    store.search_similar = MagicMock(return_value=[candidate])
    return store


@pytest.fixture
def mock_vector_store_empty() -> MagicMock:
    """Vector store that returns no similar candidates."""
    store = MagicMock()
    store.search_similar = MagicMock(return_value=[])
    return store


@pytest.fixture
def mock_call_log() -> AsyncMock:
    """Create a mock LLMCallLog recorder."""
    return AsyncMock()


@pytest.fixture
def pipeline_context() -> PipelineContext:
    """Create a PipelineContext with sample content for dedup."""
    ctx = PipelineContext()
    ctx.set("title", SAMPLE_TITLE)
    ctx.set("body_text", SAMPLE_BODY)
    ctx.set("embedding", [0.1, 0.2, 0.3, 0.4])  # mock embedding vector
    return ctx


@pytest.fixture
def dedup_processor(
    mock_gateway: AsyncMock,
    mock_vector_store_with_candidates: MagicMock,
    mock_call_log: AsyncMock,
) -> SemanticDedup:
    """Create a SemanticDedup instance with default threshold."""
    return SemanticDedup(
        gateway=mock_gateway,
        vector_store=mock_vector_store_with_candidates,
        call_log=mock_call_log,
    )


# ---------------------------------------------------------------------------
# AC-T023-4: FingerprintGenerator
# ---------------------------------------------------------------------------


class TestFingerprintGenerator:
    """Verify FingerprintGenerator produces stable SHA-256 fingerprints."""

    def test_generate_returns_sha256_hex(self) -> None:
        """generate() must return a 64-character SHA-256 hex digest string."""
        gen = FingerprintGenerator()
        fp = gen.generate(SAMPLE_TITLE, SAMPLE_BODY)
        assert isinstance(fp, str)
        assert len(fp) == 64  # SHA-256 hex digest length

    def test_same_input_produces_same_fingerprint(self) -> None:
        """Identical title+body must produce the same fingerprint."""
        gen = FingerprintGenerator()
        fp1 = gen.generate(SAMPLE_TITLE, SAMPLE_BODY)
        fp2 = gen.generate(DUPLICATE_TITLE, DUPLICATE_BODY)
        assert fp1 == fp2

    def test_different_input_produces_different_fingerprint(self) -> None:
        """Different title or body must produce a different fingerprint."""
        gen = FingerprintGenerator()
        fp_original = gen.generate(SAMPLE_TITLE, SAMPLE_BODY)
        fp_different = gen.generate(DIFFERENT_TITLE, DIFFERENT_BODY)
        assert fp_original != fp_different

    def test_case_insensitive(self) -> None:
        """Fingerprint must be case-insensitive (normalization to lowercase)."""
        gen = FingerprintGenerator()
        fp_lower = gen.generate("hello world", "some body text")
        fp_upper = gen.generate("HELLO WORLD", "SOME BODY TEXT")
        assert fp_lower == fp_upper

    def test_whitespace_insensitive(self) -> None:
        """Extra whitespace must not affect the fingerprint."""
        gen = FingerprintGenerator()
        fp_normal = gen.generate("hello world", "body text here")
        fp_extra_spaces = gen.generate("hello   world", "body   text   here")
        assert fp_normal == fp_extra_spaces

    def test_leading_trailing_whitespace_insensitive(self) -> None:
        """Leading/trailing whitespace must not affect the fingerprint."""
        gen = FingerprintGenerator()
        fp_clean = gen.generate("title", "body")
        fp_padded = gen.generate("  title  ", "  body  ")
        assert fp_clean == fp_padded


# ---------------------------------------------------------------------------
# AC-T023-1: Similarity threshold configurable
# ---------------------------------------------------------------------------


class TestSimilarityThresholdConfig:
    """Verify similarity_threshold is configurable with default 0.85."""

    def test_default_threshold_is_085(
        self,
        mock_gateway: AsyncMock,
        mock_vector_store_with_candidates: MagicMock,
        mock_call_log: AsyncMock,
    ) -> None:
        """Default similarity_threshold must be 0.85."""
        processor = SemanticDedup(
            gateway=mock_gateway,
            vector_store=mock_vector_store_with_candidates,
            call_log=mock_call_log,
        )
        assert processor.similarity_threshold == 0.85

    def test_custom_threshold(
        self,
        mock_gateway: AsyncMock,
        mock_vector_store_with_candidates: MagicMock,
        mock_call_log: AsyncMock,
    ) -> None:
        """similarity_threshold must be settable via constructor."""
        processor = SemanticDedup(
            gateway=mock_gateway,
            vector_store=mock_vector_store_with_candidates,
            call_log=mock_call_log,
            similarity_threshold=0.90,
        )
        assert processor.similarity_threshold == 0.90


# ---------------------------------------------------------------------------
# SemanticDedup implements BaseProcessor
# ---------------------------------------------------------------------------


class TestSemanticDedupInterface:
    """Verify SemanticDedup satisfies the BaseProcessor contract."""

    def test_is_subclass_of_base_processor(self) -> None:
        """SemanticDedup must be a subclass of BaseProcessor."""
        assert issubclass(SemanticDedup, BaseProcessor)

    def test_has_process_method(self, dedup_processor: SemanticDedup) -> None:
        """SemanticDedup instance must have a callable process method."""
        assert callable(getattr(dedup_processor, "process", None))

    def test_process_returns_pipeline_context(
        self,
        dedup_processor: SemanticDedup,
        pipeline_context: PipelineContext,
    ) -> None:
        """process() must return a PipelineContext instance."""
        result = dedup_processor.process(pipeline_context)
        assert isinstance(result, PipelineContext)


# ---------------------------------------------------------------------------
# AC-T023-2: Dedup flow (embedding -> vector search -> LLM judge -> mark)
# ---------------------------------------------------------------------------


class TestDedupFlow:
    """Verify the full dedup flow: vector search -> LLM judge -> mark."""

    def test_vector_search_called_with_embedding_and_threshold(
        self,
        dedup_processor: SemanticDedup,
        pipeline_context: PipelineContext,
        mock_vector_store_with_candidates: MagicMock,
    ) -> None:
        """process() must call vector_store.search_similar with embedding and threshold."""
        dedup_processor.process(pipeline_context)

        mock_vector_store_with_candidates.search_similar.assert_called_once()
        call_args = mock_vector_store_with_candidates.search_similar.call_args
        # Should pass embedding vector and threshold
        assert call_args is not None
        # The embedding from context should be passed
        args, kwargs = call_args
        # Embedding should appear in args or kwargs
        embedding = pipeline_context.get("embedding")
        passed_embedding = args[0] if args else kwargs.get("embedding")
        assert passed_embedding == embedding

    def test_llm_called_when_candidates_found(
        self,
        dedup_processor: SemanticDedup,
        pipeline_context: PipelineContext,
        mock_gateway: AsyncMock,
    ) -> None:
        """When vector search returns candidates, LLM must be called for judgment."""
        dedup_processor.process(pipeline_context)
        mock_gateway.complete.assert_called()

    def test_llm_not_called_when_no_candidates(
        self,
        mock_gateway: AsyncMock,
        mock_vector_store_empty: MagicMock,
        mock_call_log: AsyncMock,
        pipeline_context: PipelineContext,
    ) -> None:
        """When vector search returns no candidates, LLM should NOT be called."""
        processor = SemanticDedup(
            gateway=mock_gateway,
            vector_store=mock_vector_store_empty,
            call_log=mock_call_log,
        )
        processor.process(pipeline_context)
        mock_gateway.complete.assert_not_called()

    def test_duplicate_marked_when_llm_confirms(
        self,
        dedup_processor: SemanticDedup,
        pipeline_context: PipelineContext,
    ) -> None:
        """When LLM judges content as duplicate, context must be marked."""
        result_ctx = dedup_processor.process(pipeline_context)
        assert result_ctx.get("is_duplicate") is True

    def test_not_marked_duplicate_when_llm_denies(
        self,
        mock_gateway_not_duplicate: AsyncMock,
        mock_vector_store_with_candidates: MagicMock,
        mock_call_log: AsyncMock,
        pipeline_context: PipelineContext,
    ) -> None:
        """When LLM judges content as NOT duplicate, context should not be marked."""
        processor = SemanticDedup(
            gateway=mock_gateway_not_duplicate,
            vector_store=mock_vector_store_with_candidates,
            call_log=mock_call_log,
        )
        result_ctx = processor.process(pipeline_context)
        assert result_ctx.get("is_duplicate") is not True

    def test_not_marked_duplicate_when_no_candidates(
        self,
        mock_gateway: AsyncMock,
        mock_vector_store_empty: MagicMock,
        mock_call_log: AsyncMock,
        pipeline_context: PipelineContext,
    ) -> None:
        """When no candidates found, content should not be marked as duplicate."""
        processor = SemanticDedup(
            gateway=mock_gateway,
            vector_store=mock_vector_store_empty,
            call_log=mock_call_log,
        )
        result_ctx = processor.process(pipeline_context)
        assert result_ctx.get("is_duplicate") is not True


# ---------------------------------------------------------------------------
# AC-019: LLM precise duplicate determination
# ---------------------------------------------------------------------------


class TestLLMDuplicateJudgment:
    """Verify LLM is used for precise duplicate determination after vector retrieval."""

    def test_llm_receives_candidate_content_for_comparison(
        self,
        dedup_processor: SemanticDedup,
        pipeline_context: PipelineContext,
        mock_gateway: AsyncMock,
    ) -> None:
        """LLM call must include both the new content and the candidate for comparison."""
        dedup_processor.process(pipeline_context)
        mock_gateway.complete.assert_called_once()
        call_args = mock_gateway.complete.call_args
        # The prompt should contain both the new content and the candidate
        assert call_args is not None
        # Flatten all args to string to check content presence
        all_str_args = str(call_args)
        assert SAMPLE_TITLE in all_str_args or SAMPLE_BODY in all_str_args


# ---------------------------------------------------------------------------
# AC-022: Unique fingerprint per content, idempotent processing
# ---------------------------------------------------------------------------


class TestFingerprintIdempotency:
    """Verify fingerprint-based idempotent processing."""

    def test_fingerprint_set_in_context(
        self,
        dedup_processor: SemanticDedup,
        pipeline_context: PipelineContext,
    ) -> None:
        """process() must set a 'fingerprint' key in the context."""
        result_ctx = dedup_processor.process(pipeline_context)
        fingerprint = result_ctx.get("fingerprint")
        assert fingerprint is not None
        assert isinstance(fingerprint, str)
        assert len(fingerprint) == 64  # SHA-256 hex digest

    def test_same_content_produces_same_fingerprint_in_context(
        self,
        mock_gateway: AsyncMock,
        mock_vector_store_empty: MagicMock,
        mock_call_log: AsyncMock,
    ) -> None:
        """Processing the same content twice must yield the same fingerprint."""
        processor1 = SemanticDedup(
            gateway=mock_gateway,
            vector_store=mock_vector_store_empty,
            call_log=mock_call_log,
        )
        processor2 = SemanticDedup(
            gateway=AsyncMock(),
            vector_store=MagicMock(search_similar=MagicMock(return_value=[])),
            call_log=AsyncMock(),
        )

        ctx1 = PipelineContext()
        ctx1.set("title", SAMPLE_TITLE)
        ctx1.set("body_text", SAMPLE_BODY)
        ctx1.set("embedding", [0.1, 0.2])

        ctx2 = PipelineContext()
        ctx2.set("title", DUPLICATE_TITLE)
        ctx2.set("body_text", DUPLICATE_BODY)
        ctx2.set("embedding", [0.1, 0.2])

        result1 = processor1.process(ctx1)
        result2 = processor2.process(ctx2)

        assert result1.get("fingerprint") == result2.get("fingerprint")


# ---------------------------------------------------------------------------
# AC-T023-3: Fallback logic (fingerprint + SimHash)
# ---------------------------------------------------------------------------


class TestFallbackLogic:
    """Verify degradation to fingerprint + SimHash when LLM/vector unavailable."""

    def test_fallback_on_gateway_error(
        self,
        mock_vector_store_with_candidates: MagicMock,
        mock_call_log: AsyncMock,
        pipeline_context: PipelineContext,
    ) -> None:
        """When LLM gateway raises an error, fallback to fingerprint+SimHash."""
        failing_gateway = AsyncMock()
        failing_gateway.complete = AsyncMock(side_effect=Exception("LLM unavailable"))

        processor = SemanticDedup(
            gateway=failing_gateway,
            vector_store=mock_vector_store_with_candidates,
            call_log=mock_call_log,
        )
        # Should not raise; should degrade gracefully
        result_ctx = processor.process(pipeline_context)
        # Fallback should still produce a fingerprint
        assert result_ctx.get("fingerprint") is not None
        # Should indicate fallback was used
        assert result_ctx.get("dedup_fallback") is True

    def test_fallback_on_vector_store_error(
        self,
        mock_gateway: AsyncMock,
        mock_call_log: AsyncMock,
        pipeline_context: PipelineContext,
    ) -> None:
        """When vector store raises an error, fallback to fingerprint+SimHash."""
        failing_store = MagicMock()
        failing_store.search_similar = MagicMock(
            side_effect=Exception("Vector store unavailable")
        )

        processor = SemanticDedup(
            gateway=mock_gateway,
            vector_store=failing_store,
            call_log=mock_call_log,
        )
        result_ctx = processor.process(pipeline_context)
        assert result_ctx.get("fingerprint") is not None
        assert result_ctx.get("dedup_fallback") is True

    def test_fallback_uses_simhash_for_similarity(
        self,
        mock_call_log: AsyncMock,
        pipeline_context: PipelineContext,
    ) -> None:
        """Fallback path should use SimHash-based similarity comparison."""
        failing_gateway = AsyncMock()
        failing_gateway.complete = AsyncMock(side_effect=Exception("LLM unavailable"))
        failing_store = MagicMock()
        failing_store.search_similar = MagicMock(
            side_effect=Exception("Vector store unavailable")
        )

        processor = SemanticDedup(
            gateway=failing_gateway,
            vector_store=failing_store,
            call_log=mock_call_log,
        )
        result_ctx = processor.process(pipeline_context)
        # Fallback mode should set dedup method indicator
        assert result_ctx.get("dedup_method") == "simhash"


# ---------------------------------------------------------------------------
# Edge cases / boundary conditions
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Boundary conditions and edge cases for dedup processing."""

    def test_empty_body_text(
        self,
        mock_gateway: AsyncMock,
        mock_vector_store_empty: MagicMock,
        mock_call_log: AsyncMock,
    ) -> None:
        """Processing with empty body_text should not raise."""
        processor = SemanticDedup(
            gateway=mock_gateway,
            vector_store=mock_vector_store_empty,
            call_log=mock_call_log,
        )
        ctx = PipelineContext()
        ctx.set("title", "Some Title")
        ctx.set("body_text", "")
        ctx.set("embedding", [0.0])
        result = processor.process(ctx)
        assert isinstance(result, PipelineContext)
        # Fingerprint should still be generated
        assert result.get("fingerprint") is not None

    def test_threshold_boundary_below(
        self,
        mock_gateway: AsyncMock,
        mock_call_log: AsyncMock,
    ) -> None:
        """Candidates below threshold should be excluded from LLM judgment."""
        store = MagicMock()
        # search_similar returns empty when threshold filters out low-score results
        store.search_similar = MagicMock(return_value=[])

        processor = SemanticDedup(
            gateway=mock_gateway,
            vector_store=store,
            call_log=mock_call_log,
            similarity_threshold=0.95,
        )
        ctx = PipelineContext()
        ctx.set("title", SAMPLE_TITLE)
        ctx.set("body_text", SAMPLE_BODY)
        ctx.set("embedding", [0.1, 0.2])
        result = processor.process(ctx)
        # No candidates -> LLM not called -> not duplicate
        mock_gateway.complete.assert_not_called()
        assert result.get("is_duplicate") is not True
