"""Tests for DigestGenerator summarization processor.

Covers:
- AC-023: DigestGenerator generates comprehensive digest for clustered documents
         (including timeline and key points)
- AC-025: All processors support degradation to traditional logic
- AC-T025-1: DigestGenerator output contains title/summary/timeline/key_points
- AC-T025-3: Summarization degradation uses truncation (first N sentences)
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from intellisource.llm.processors.summarizer import DigestGenerator

from intellisource.pipeline.base import BaseProcessor
from intellisource.pipeline.context import PipelineContext

# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

SAMPLE_CLUSTER_CONTENTS: list[dict[str, str]] = [
    {
        "title": "AI Breakthrough in Healthcare",
        "body_text": (
            "Researchers announced a new AI model for early cancer detection. "
            "The model achieves 95% accuracy on benchmark datasets. "
            "Clinical trials are expected to begin next quarter."
        ),
        "published_at": "2026-03-01T10:00:00Z",
    },
    {
        "title": "Follow-up Study on AI Cancer Detection",
        "body_text": (
            "A follow-up study confirmed the initial findings. "
            "The model was tested across three hospitals. "
            "Results showed consistent performance in diverse populations."
        ),
        "published_at": "2026-03-15T14:30:00Z",
    },
    {
        "title": "FDA Reviews AI Diagnostic Tools",
        "body_text": (
            "The FDA has begun reviewing AI-based diagnostic tools. "
            "New guidelines for AI in medical devices are expected. "
            "Industry leaders welcome the regulatory clarity."
        ),
        "published_at": "2026-04-01T09:00:00Z",
    },
]

SAMPLE_LLM_DIGEST_OUTPUT = json.dumps(
    {
        "title": "AI in Healthcare: From Breakthrough to Regulation",
        "summary": (
            "A series of developments in AI-based cancer detection, "
            "from initial research breakthroughs to FDA regulatory review."
        ),
        "timeline": [
            {
                "date": "2026-03-01",
                "event": "AI cancer detection model announced with 95% accuracy",
            },
            {
                "date": "2026-03-15",
                "event": "Follow-up study confirms findings across three hospitals",
            },
            {"date": "2026-04-01", "event": "FDA begins reviewing AI diagnostic tools"},
        ],
        "key_points": [
            "AI model achieves 95% accuracy in early cancer detection",
            "Results validated across diverse populations",
            "FDA initiating regulatory framework for AI diagnostics",
        ],
    }
)

SINGLE_DOC_CLUSTER: list[dict[str, str]] = [
    {
        "title": "Standalone Article",
        "body_text": (
            "First sentence of the article. "
            "Second sentence with details. "
            "Third sentence concludes the topic. "
            "Fourth sentence adds context. "
            "Fifth sentence wraps up."
        ),
        "published_at": "2026-04-05T12:00:00Z",
    },
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_gateway() -> AsyncMock:
    """Create a mock LLMGateway that returns a valid digest JSON."""
    gateway = AsyncMock()
    result = MagicMock()
    result.content = SAMPLE_LLM_DIGEST_OUTPUT
    result.metadata = {
        "input_tokens": 500,
        "output_tokens": 200,
        "latency_ms": 1200.0,
        "model": "gpt-4o-mini",
    }
    gateway.complete = AsyncMock(return_value=result)
    return gateway


@pytest.fixture
def mock_gateway_failing() -> AsyncMock:
    """Create a mock LLMGateway that always raises an error."""
    gateway = AsyncMock()
    gateway.complete = AsyncMock(side_effect=RuntimeError("LLM unavailable"))
    return gateway


@pytest.fixture
def mock_call_log() -> AsyncMock:
    """Create a mock LLMCallLog recorder."""
    return AsyncMock()


@pytest.fixture
def pipeline_context() -> PipelineContext:
    """Create a PipelineContext with sample cluster contents."""
    ctx = PipelineContext()
    ctx.set("cluster_contents", SAMPLE_CLUSTER_CONTENTS)
    return ctx


@pytest.fixture
def digest_generator(
    mock_gateway: AsyncMock,
    mock_call_log: AsyncMock,
) -> DigestGenerator:
    """Create a DigestGenerator with mocked dependencies."""
    return DigestGenerator(gateway=mock_gateway, call_log=mock_call_log)


# ---------------------------------------------------------------------------
# DigestGenerator implements BaseProcessor
# ---------------------------------------------------------------------------


class TestDigestGeneratorInterface:
    """Verify DigestGenerator satisfies the BaseProcessor contract."""

    def test_is_subclass_of_base_processor(self) -> None:
        """DigestGenerator must be a subclass of BaseProcessor."""
        assert issubclass(DigestGenerator, BaseProcessor)

    def test_has_process_method(self, digest_generator: DigestGenerator) -> None:
        """DigestGenerator instance must expose a callable process method."""
        assert callable(getattr(digest_generator, "process", None))

    def test_process_accepts_pipeline_context(
        self, digest_generator: DigestGenerator
    ) -> None:
        """process() signature must include a 'context' parameter."""
        import inspect

        sig = inspect.signature(digest_generator.process)
        params = list(sig.parameters.keys())
        assert "context" in params

    def test_process_returns_pipeline_context(
        self,
        digest_generator: DigestGenerator,
        pipeline_context: PipelineContext,
    ) -> None:
        """process() must return a PipelineContext instance."""
        result = digest_generator.process(pipeline_context)
        assert isinstance(result, PipelineContext)


# ---------------------------------------------------------------------------
# AC-023: Comprehensive digest from clustered documents
# ---------------------------------------------------------------------------


class TestDigestGeneration:
    """Verify LLM-based digest generation for clustered documents."""

    def test_llm_called_with_cluster_contents(
        self,
        digest_generator: DigestGenerator,
        pipeline_context: PipelineContext,
        mock_gateway: AsyncMock,
    ) -> None:
        """process() must invoke the LLM gateway to generate a digest."""
        digest_generator.process(pipeline_context)
        mock_gateway.complete.assert_called_once()

    def test_digest_set_in_context(
        self,
        digest_generator: DigestGenerator,
        pipeline_context: PipelineContext,
    ) -> None:
        """process() must store the digest under the 'digest' key in context."""
        result_ctx = digest_generator.process(pipeline_context)
        digest = result_ctx.get("digest")
        assert digest is not None
        assert isinstance(digest, dict)

    def test_digest_contains_title(
        self,
        digest_generator: DigestGenerator,
        pipeline_context: PipelineContext,
    ) -> None:
        """The digest dict must contain a 'title' field (non-empty string)."""
        result_ctx = digest_generator.process(pipeline_context)
        digest = result_ctx.get("digest")
        assert digest is not None
        assert "title" in digest
        assert isinstance(digest["title"], str)
        assert len(digest["title"]) > 0

    def test_digest_contains_summary(
        self,
        digest_generator: DigestGenerator,
        pipeline_context: PipelineContext,
    ) -> None:
        """The digest dict must contain a 'summary' field (non-empty string)."""
        result_ctx = digest_generator.process(pipeline_context)
        digest = result_ctx.get("digest")
        assert digest is not None
        assert "summary" in digest
        assert isinstance(digest["summary"], str)
        assert len(digest["summary"]) > 0

    def test_digest_contains_timeline(
        self,
        digest_generator: DigestGenerator,
        pipeline_context: PipelineContext,
    ) -> None:
        """The digest dict must contain a 'timeline' field (list of events)."""
        result_ctx = digest_generator.process(pipeline_context)
        digest = result_ctx.get("digest")
        assert digest is not None
        assert "timeline" in digest
        assert isinstance(digest["timeline"], list)
        assert len(digest["timeline"]) > 0

    def test_digest_contains_key_points(
        self,
        digest_generator: DigestGenerator,
        pipeline_context: PipelineContext,
    ) -> None:
        """The digest dict must contain a 'key_points' field (list of strings)."""
        result_ctx = digest_generator.process(pipeline_context)
        digest = result_ctx.get("digest")
        assert digest is not None
        assert "key_points" in digest
        assert isinstance(digest["key_points"], list)
        assert len(digest["key_points"]) > 0

    def test_digest_preserves_existing_context_keys(
        self,
        digest_generator: DigestGenerator,
        pipeline_context: PipelineContext,
    ) -> None:
        """Generating a digest must not clobber pre-existing context keys."""
        pipeline_context.set("source_id", "cluster-001")
        result_ctx = digest_generator.process(pipeline_context)
        assert result_ctx.get("source_id") == "cluster-001"
        assert result_ctx.get("cluster_contents") is not None


# ---------------------------------------------------------------------------
# AC-T025-1: Output structure validation
# ---------------------------------------------------------------------------


class TestDigestOutputStructure:
    """Verify the digest output contains exactly the required fields."""

    def test_digest_has_all_required_keys(
        self,
        digest_generator: DigestGenerator,
        pipeline_context: PipelineContext,
    ) -> None:
        """Digest must contain all four keys: title, summary, timeline, key_points."""
        result_ctx = digest_generator.process(pipeline_context)
        digest = result_ctx.get("digest")
        assert digest is not None
        required_keys = {"title", "summary", "timeline", "key_points"}
        assert required_keys.issubset(set(digest.keys()))

    def test_timeline_entries_have_date_and_event(
        self,
        digest_generator: DigestGenerator,
        pipeline_context: PipelineContext,
    ) -> None:
        """Each timeline entry should have 'date' and 'event' fields."""
        result_ctx = digest_generator.process(pipeline_context)
        digest = result_ctx.get("digest")
        assert digest is not None
        for entry in digest["timeline"]:
            assert "date" in entry
            assert "event" in entry

    def test_key_points_are_strings(
        self,
        digest_generator: DigestGenerator,
        pipeline_context: PipelineContext,
    ) -> None:
        """Each key point must be a string."""
        result_ctx = digest_generator.process(pipeline_context)
        digest = result_ctx.get("digest")
        assert digest is not None
        for kp in digest["key_points"]:
            assert isinstance(kp, str)


# ---------------------------------------------------------------------------
# AC-025 + AC-T025-3: Degradation to truncation-based summary
# ---------------------------------------------------------------------------


class TestDigestDegradation:
    """Verify fallback to truncation-based summary when LLM fails."""

    def test_degrade_on_llm_exception(
        self,
        mock_gateway_failing: AsyncMock,
        mock_call_log: AsyncMock,
        pipeline_context: PipelineContext,
    ) -> None:
        """When LLM raises an exception, process() must not raise and must produce a digest."""
        generator = DigestGenerator(
            gateway=mock_gateway_failing, call_log=mock_call_log
        )
        result_ctx = generator.process(pipeline_context)
        digest = result_ctx.get("digest")
        assert digest is not None
        assert isinstance(digest, dict)

    def test_degraded_digest_has_required_keys(
        self,
        mock_gateway_failing: AsyncMock,
        mock_call_log: AsyncMock,
        pipeline_context: PipelineContext,
    ) -> None:
        """Degraded digest must still contain title/summary/timeline/key_points."""
        generator = DigestGenerator(
            gateway=mock_gateway_failing, call_log=mock_call_log
        )
        result_ctx = generator.process(pipeline_context)
        digest = result_ctx.get("digest")
        assert digest is not None
        required_keys = {"title", "summary", "timeline", "key_points"}
        assert required_keys.issubset(set(digest.keys()))

    def test_degraded_summary_uses_truncation(
        self,
        mock_gateway_failing: AsyncMock,
        mock_call_log: AsyncMock,
    ) -> None:
        """Degraded summary should be a truncation of the first N sentences from body_text."""
        ctx = PipelineContext()
        ctx.set("cluster_contents", SINGLE_DOC_CLUSTER)

        generator = DigestGenerator(
            gateway=mock_gateway_failing, call_log=mock_call_log
        )
        result_ctx = generator.process(ctx)
        digest = result_ctx.get("digest")
        assert digest is not None

        # The summary should contain content from the beginning of the body text
        # (first 3 sentences per contract)
        summary = digest["summary"]
        assert "First sentence" in summary
        assert isinstance(summary, str)
        assert len(summary) > 0

    def test_degraded_digest_does_not_retry_llm(
        self,
        mock_gateway_failing: AsyncMock,
        mock_call_log: AsyncMock,
        pipeline_context: PipelineContext,
    ) -> None:
        """Once LLM fails, degradation must not make additional LLM calls."""
        generator = DigestGenerator(
            gateway=mock_gateway_failing, call_log=mock_call_log
        )
        generator.process(pipeline_context)
        assert mock_gateway_failing.complete.call_count == 1

    def test_degrade_on_invalid_json_response(
        self,
        mock_call_log: AsyncMock,
        pipeline_context: PipelineContext,
    ) -> None:
        """When LLM returns non-JSON, degrade to truncation-based summary."""
        gateway = AsyncMock()
        bad_result = MagicMock()
        bad_result.content = "This is not valid JSON"
        bad_result.metadata = {
            "input_tokens": 100,
            "output_tokens": 20,
            "latency_ms": 150.0,
            "model": "gpt-4o-mini",
        }
        gateway.complete = AsyncMock(return_value=bad_result)

        generator = DigestGenerator(gateway=gateway, call_log=mock_call_log)
        result_ctx = generator.process(pipeline_context)
        digest = result_ctx.get("digest")
        assert digest is not None
        assert isinstance(digest, dict)
        required_keys = {"title", "summary", "timeline", "key_points"}
        assert required_keys.issubset(set(digest.keys()))


# ---------------------------------------------------------------------------
# Edge cases / boundary conditions
# ---------------------------------------------------------------------------


class TestDigestEdgeCases:
    """Boundary conditions and edge cases for digest generation."""

    def test_empty_cluster_contents(
        self,
        digest_generator: DigestGenerator,
    ) -> None:
        """Processing with empty cluster_contents should handle gracefully."""
        ctx = PipelineContext()
        ctx.set("cluster_contents", [])

        result_ctx = digest_generator.process(ctx)
        digest = result_ctx.get("digest")
        assert digest is not None
        assert isinstance(digest, dict)

    def test_single_document_cluster(
        self,
        digest_generator: DigestGenerator,
    ) -> None:
        """Processing with a single document should still produce a valid digest."""
        ctx = PipelineContext()
        ctx.set("cluster_contents", SINGLE_DOC_CLUSTER)

        result_ctx = digest_generator.process(ctx)
        digest = result_ctx.get("digest")
        assert digest is not None
        assert "title" in digest

    def test_missing_cluster_contents_raises(
        self,
        digest_generator: DigestGenerator,
    ) -> None:
        """When cluster_contents key is missing, should raise ValueError or KeyError."""
        ctx = PipelineContext()
        with pytest.raises((ValueError, KeyError)):
            digest_generator.process(ctx)
