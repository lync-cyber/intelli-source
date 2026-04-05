"""Tests for LLMExtractor structured extraction processor.

Covers:
- AC-018: Traditional parsing fails -> call LLM to extract structured data per JSON Schema
- AC-021: LLM output non-compliant -> degrade to traditional processing (regex/rules)
- AC-T022-1: LLMExtractor implements BaseProcessor interface
- AC-T022-2: Extraction result written to ProcessedContent.structured_data field
- AC-T022-3: Degradation logic uses rule engine + regex extraction (arch S5.3)
- AC-T022-4: Extraction events recorded to LLMCallLog (call_type=extract)
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from intellisource.llm.processors.extractor import LLMExtractor

from intellisource.pipeline.base import BaseProcessor
from intellisource.pipeline.context import PipelineContext

# ---------------------------------------------------------------------------
# Sample data and schemas
# ---------------------------------------------------------------------------

SAMPLE_EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "authors": {"type": "array", "items": {"type": "string"}},
        "date": {"type": "string"},
        "keywords": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title"],
}

SAMPLE_BODY_TEXT = (
    "Title: Introduction to Machine Learning\n"
    "Authors: Alice Smith, Bob Jones\n"
    "Date: 2025-01-15\n"
    "Keywords: ML, AI, deep learning\n"
    "This paper introduces fundamental concepts of machine learning."
)

SAMPLE_LLM_VALID_OUTPUT = json.dumps(
    {
        "title": "Introduction to Machine Learning",
        "authors": ["Alice Smith", "Bob Jones"],
        "date": "2025-01-15",
        "keywords": ["ML", "AI", "deep learning"],
    }
)

SAMPLE_LLM_INVALID_OUTPUT = "This is not valid JSON at all."

SAMPLE_LLM_SCHEMA_VIOLATION_OUTPUT = json.dumps(
    {
        # Missing required "title" field
        "authors": ["Alice Smith"],
    }
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_gateway() -> AsyncMock:
    """Create a mock LLMGateway that returns valid extraction JSON."""
    gateway = AsyncMock()
    result = MagicMock()
    result.content = SAMPLE_LLM_VALID_OUTPUT
    result.metadata = {
        "input_tokens": 100,
        "output_tokens": 50,
        "latency_ms": 200.0,
        "model": "gpt-4o-mini",
    }
    gateway.complete = AsyncMock(return_value=result)
    return gateway


@pytest.fixture
def mock_call_log() -> AsyncMock:
    """Create a mock LLMCallLog recorder."""
    return AsyncMock()


@pytest.fixture
def pipeline_context() -> PipelineContext:
    """Create a PipelineContext with sample body text."""
    ctx = PipelineContext()
    ctx.set("body_text", SAMPLE_BODY_TEXT)
    return ctx


@pytest.fixture
def extractor(mock_gateway: AsyncMock, mock_call_log: AsyncMock) -> LLMExtractor:
    """Create an LLMExtractor instance with mocked dependencies."""
    return LLMExtractor(
        gateway=mock_gateway,
        call_log=mock_call_log,
        extraction_schema=SAMPLE_EXTRACTION_SCHEMA,
    )


# ---------------------------------------------------------------------------
# AC-T022-1: LLMExtractor implements BaseProcessor interface
# ---------------------------------------------------------------------------


class TestLLMExtractorInterface:
    """Verify LLMExtractor satisfies the BaseProcessor contract."""

    def test_is_subclass_of_base_processor(self) -> None:
        """LLMExtractor must be a subclass of BaseProcessor."""
        assert issubclass(LLMExtractor, BaseProcessor)

    def test_has_process_method(self, extractor: LLMExtractor) -> None:
        """LLMExtractor instance must have a process method."""
        assert callable(getattr(extractor, "process", None))

    def test_process_accepts_pipeline_context(self, extractor: LLMExtractor) -> None:
        """process() must accept PipelineContext and return PipelineContext."""
        import inspect

        sig = inspect.signature(extractor.process)
        params = list(sig.parameters.keys())
        # Should have 'context' parameter (besides self)
        assert "context" in params


# ---------------------------------------------------------------------------
# AC-018: Traditional parsing fails -> LLM extraction
# ---------------------------------------------------------------------------


class TestLLMExtraction:
    """Verify LLM-based structured data extraction."""

    @pytest.mark.asyncio
    async def test_llm_extracts_structured_data_on_traditional_failure(
        self,
        extractor: LLMExtractor,
        pipeline_context: PipelineContext,
        mock_gateway: AsyncMock,
    ) -> None:
        """When traditional parsing fails, LLM should be called to extract data."""
        # Mark traditional parsing as failed in context
        pipeline_context.set("traditional_parse_failed", True)

        result_ctx = extractor.process(pipeline_context)

        # LLM gateway should have been called
        mock_gateway.complete.assert_called_once()
        # The call should include extraction-related parameters
        call_kwargs = mock_gateway.complete.call_args
        assert call_kwargs is not None

    @pytest.mark.asyncio
    async def test_llm_output_conforms_to_json_schema(
        self,
        extractor: LLMExtractor,
        pipeline_context: PipelineContext,
    ) -> None:
        """LLM extraction result should conform to the provided JSON Schema."""
        pipeline_context.set("traditional_parse_failed", True)

        result_ctx = extractor.process(pipeline_context)

        structured = result_ctx.get("structured_data")
        assert structured is not None
        assert isinstance(structured, dict)
        # Must have required 'title' field per schema
        assert "title" in structured
        assert structured["title"] == "Introduction to Machine Learning"

    @pytest.mark.asyncio
    async def test_llm_extracts_all_schema_fields(
        self,
        extractor: LLMExtractor,
        pipeline_context: PipelineContext,
    ) -> None:
        """LLM should extract all fields defined in the extraction schema."""
        pipeline_context.set("traditional_parse_failed", True)

        result_ctx = extractor.process(pipeline_context)

        structured = result_ctx.get("structured_data")
        assert structured is not None
        assert structured["authors"] == ["Alice Smith", "Bob Jones"]
        assert structured["date"] == "2025-01-15"
        assert structured["keywords"] == ["ML", "AI", "deep learning"]


# ---------------------------------------------------------------------------
# AC-T022-2: Extraction result written to ProcessedContent.structured_data
# ---------------------------------------------------------------------------


class TestStructuredDataOutput:
    """Verify extraction results are written to structured_data in context."""

    @pytest.mark.asyncio
    async def test_result_written_to_structured_data_key(
        self,
        extractor: LLMExtractor,
        pipeline_context: PipelineContext,
    ) -> None:
        """Extraction result must be stored under 'structured_data' key."""
        pipeline_context.set("traditional_parse_failed", True)

        result_ctx = extractor.process(pipeline_context)

        assert result_ctx.get("structured_data") is not None
        assert isinstance(result_ctx.get("structured_data"), dict)

    @pytest.mark.asyncio
    async def test_structured_data_preserves_existing_context(
        self,
        extractor: LLMExtractor,
        pipeline_context: PipelineContext,
    ) -> None:
        """Writing structured_data should not clobber existing context keys."""
        pipeline_context.set("traditional_parse_failed", True)
        pipeline_context.set("source_id", "test-source-123")

        result_ctx = extractor.process(pipeline_context)

        # Original keys preserved
        assert result_ctx.get("source_id") == "test-source-123"
        assert result_ctx.get("body_text") == SAMPLE_BODY_TEXT
        # New key added
        assert result_ctx.get("structured_data") is not None


# ---------------------------------------------------------------------------
# AC-021 / AC-T022-3: Degradation to regex/rule extraction
# ---------------------------------------------------------------------------


class TestDegradation:
    """Verify fallback to regex/rule-based extraction when LLM fails."""

    @pytest.mark.asyncio
    async def test_degrade_on_invalid_json_response(
        self,
        extractor: LLMExtractor,
        pipeline_context: PipelineContext,
        mock_gateway: AsyncMock,
    ) -> None:
        """When LLM returns invalid JSON, degrade to regex extraction."""
        pipeline_context.set("traditional_parse_failed", True)

        # Make LLM return non-JSON
        bad_result = MagicMock()
        bad_result.content = SAMPLE_LLM_INVALID_OUTPUT
        bad_result.metadata = {
            "input_tokens": 100,
            "output_tokens": 20,
            "latency_ms": 150.0,
            "model": "gpt-4o-mini",
        }
        mock_gateway.complete = AsyncMock(return_value=bad_result)

        result_ctx = extractor.process(pipeline_context)

        # Should still produce structured_data via regex fallback
        structured = result_ctx.get("structured_data")
        assert structured is not None
        assert isinstance(structured, dict)

    @pytest.mark.asyncio
    async def test_degrade_on_schema_violation(
        self,
        extractor: LLMExtractor,
        pipeline_context: PipelineContext,
        mock_gateway: AsyncMock,
    ) -> None:
        """When LLM output violates schema, degrade to regex extraction."""
        pipeline_context.set("traditional_parse_failed", True)

        # Make LLM return JSON that violates schema (missing required 'title')
        bad_result = MagicMock()
        bad_result.content = SAMPLE_LLM_SCHEMA_VIOLATION_OUTPUT
        bad_result.metadata = {
            "input_tokens": 100,
            "output_tokens": 30,
            "latency_ms": 180.0,
            "model": "gpt-4o-mini",
        }
        mock_gateway.complete = AsyncMock(return_value=bad_result)

        result_ctx = extractor.process(pipeline_context)

        # Should still produce structured_data via regex fallback
        structured = result_ctx.get("structured_data")
        assert structured is not None
        assert isinstance(structured, dict)

    @pytest.mark.asyncio
    async def test_degrade_on_llm_exception(
        self,
        extractor: LLMExtractor,
        pipeline_context: PipelineContext,
        mock_gateway: AsyncMock,
    ) -> None:
        """When LLM call raises an exception, degrade to regex extraction."""
        pipeline_context.set("traditional_parse_failed", True)

        mock_gateway.complete = AsyncMock(side_effect=RuntimeError("LLM unavailable"))

        result_ctx = extractor.process(pipeline_context)

        structured = result_ctx.get("structured_data")
        assert structured is not None
        assert isinstance(structured, dict)

    @pytest.mark.asyncio
    async def test_regex_fallback_extracts_title(
        self,
        extractor: LLMExtractor,
        pipeline_context: PipelineContext,
        mock_gateway: AsyncMock,
    ) -> None:
        """Regex fallback should extract title from 'Title: ...' pattern."""
        pipeline_context.set("traditional_parse_failed", True)

        mock_gateway.complete = AsyncMock(side_effect=RuntimeError("LLM down"))

        result_ctx = extractor.process(pipeline_context)

        structured = result_ctx.get("structured_data")
        assert structured is not None
        # Regex should extract title from "Title: Introduction to Machine Learning"
        assert "title" in structured
        assert "Introduction to Machine Learning" in structured["title"]

    @pytest.mark.asyncio
    async def test_regex_fallback_extracts_authors(
        self,
        extractor: LLMExtractor,
        pipeline_context: PipelineContext,
        mock_gateway: AsyncMock,
    ) -> None:
        """Regex fallback should extract authors from 'Authors: ...' pattern."""
        pipeline_context.set("traditional_parse_failed", True)

        mock_gateway.complete = AsyncMock(side_effect=RuntimeError("LLM down"))

        result_ctx = extractor.process(pipeline_context)

        structured = result_ctx.get("structured_data")
        assert structured is not None
        assert "authors" in structured
        assert isinstance(structured["authors"], list)
        assert len(structured["authors"]) >= 1

    @pytest.mark.asyncio
    async def test_regex_fallback_extracts_keywords(
        self,
        extractor: LLMExtractor,
        pipeline_context: PipelineContext,
        mock_gateway: AsyncMock,
    ) -> None:
        """Regex fallback should extract keywords from 'Keywords: ...' pattern."""
        pipeline_context.set("traditional_parse_failed", True)

        mock_gateway.complete = AsyncMock(side_effect=RuntimeError("LLM down"))

        result_ctx = extractor.process(pipeline_context)

        structured = result_ctx.get("structured_data")
        assert structured is not None
        assert "keywords" in structured
        assert isinstance(structured["keywords"], list)

    @pytest.mark.asyncio
    async def test_degradation_does_not_call_llm_when_already_failed(
        self,
        extractor: LLMExtractor,
        pipeline_context: PipelineContext,
        mock_gateway: AsyncMock,
    ) -> None:
        """Once LLM fails, regex fallback must not make additional LLM calls."""
        pipeline_context.set("traditional_parse_failed", True)

        mock_gateway.complete = AsyncMock(side_effect=RuntimeError("LLM down"))

        extractor.process(pipeline_context)

        # LLM was called exactly once (the failed attempt), not retried
        assert mock_gateway.complete.call_count == 1


# ---------------------------------------------------------------------------
# AC-T022-4: Extraction events recorded to LLMCallLog
# ---------------------------------------------------------------------------


class TestCallLogging:
    """Verify extraction events are recorded to LLMCallLog."""

    @pytest.mark.asyncio
    async def test_successful_extraction_logged_with_call_type_extract(
        self,
        extractor: LLMExtractor,
        pipeline_context: PipelineContext,
        mock_call_log: AsyncMock,
    ) -> None:
        """Successful LLM extraction must log with call_type='extract'."""
        pipeline_context.set("traditional_parse_failed", True)

        extractor.process(pipeline_context)

        mock_call_log.record.assert_called()
        call_kwargs = mock_call_log.record.call_args
        assert call_kwargs is not None
        # Extract either positional or keyword args
        if call_kwargs.kwargs:
            assert call_kwargs.kwargs.get("call_type") == "extract"
        else:
            # Check all calls for call_type=extract
            found = False
            for c in mock_call_log.record.call_args_list:
                if c.kwargs.get("call_type") == "extract":
                    found = True
                    break
            assert found, "No log record with call_type='extract' found"

    @pytest.mark.asyncio
    async def test_failed_extraction_logged_with_fallback_status(
        self,
        extractor: LLMExtractor,
        pipeline_context: PipelineContext,
        mock_gateway: AsyncMock,
        mock_call_log: AsyncMock,
    ) -> None:
        """When LLM fails and degrades, log entry should reflect fallback status."""
        pipeline_context.set("traditional_parse_failed", True)

        mock_gateway.complete = AsyncMock(side_effect=RuntimeError("LLM down"))

        extractor.process(pipeline_context)

        mock_call_log.record.assert_called()
        # Should have logged with status indicating fallback
        found_fallback = False
        for c in mock_call_log.record.call_args_list:
            if c.kwargs.get("status") == "fallback":
                found_fallback = True
                break
        assert found_fallback, "No log record with status='fallback' found"

    @pytest.mark.asyncio
    async def test_log_includes_token_metadata(
        self,
        extractor: LLMExtractor,
        pipeline_context: PipelineContext,
        mock_call_log: AsyncMock,
    ) -> None:
        """Log entry should include token usage metadata."""
        pipeline_context.set("traditional_parse_failed", True)

        extractor.process(pipeline_context)

        mock_call_log.record.assert_called()
        call_kwargs = mock_call_log.record.call_args
        assert call_kwargs is not None
        kwargs = call_kwargs.kwargs
        # Should log token counts from LLM metadata
        assert "input_tokens" in kwargs or "metadata" in kwargs


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge case and boundary condition tests."""

    @pytest.mark.asyncio
    async def test_empty_body_text(
        self,
        extractor: LLMExtractor,
        mock_gateway: AsyncMock,
    ) -> None:
        """When body_text is empty, extractor should handle gracefully."""
        ctx = PipelineContext()
        ctx.set("body_text", "")
        ctx.set("traditional_parse_failed", True)

        result_ctx = extractor.process(ctx)

        # Should not raise; structured_data may be empty dict or minimal
        structured = result_ctx.get("structured_data")
        assert structured is not None
        assert isinstance(structured, dict)

    @pytest.mark.asyncio
    async def test_missing_body_text_key(
        self,
        extractor: LLMExtractor,
    ) -> None:
        """When body_text key is missing from context, should handle gracefully."""
        ctx = PipelineContext()
        ctx.set("traditional_parse_failed", True)

        # Should either raise a clear error or produce empty structured_data
        # We expect a ValueError or similar for missing input
        with pytest.raises((ValueError, KeyError)):
            extractor.process(ctx)

    @pytest.mark.asyncio
    async def test_process_returns_pipeline_context(
        self,
        extractor: LLMExtractor,
        pipeline_context: PipelineContext,
    ) -> None:
        """process() must return a PipelineContext instance."""
        pipeline_context.set("traditional_parse_failed", True)

        result = extractor.process(pipeline_context)

        assert isinstance(result, PipelineContext)
