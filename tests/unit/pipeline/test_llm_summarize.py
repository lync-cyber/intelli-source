"""Tests for llm_summarize in pipeline/processors/tools.py.

Covers AC-023 P2: structured digest with timeline/key_points via LLM,
with fallback to truncate_summary on failure.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from intellisource.pipeline.processors.tools import (
    DIGEST_SCHEMA,
    llm_summarize,
    truncate_summary,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_DIGEST = {
    "title": "AI Advances in 2024",
    "summary": "Researchers made significant breakthroughs in large language models.",
    "timeline": [
        {"date": "2024-01", "event": "GPT-5 released"},
        {"date": "2024-06", "event": "New benchmark set"},
    ],
    "key_points": ["Scaling laws continue to hold", "Multimodal models improve"],
}

_CLUSTER_CONTENTS: list[dict[str, str]] = [
    {
        "title": "AI Advances in 2024",
        "body_text": (
            "Researchers made significant breakthroughs in large language models."
        ),
        "published_at": "2024-01-15",
    },
    {
        "title": "Benchmark Records Broken",
        "body_text": "New benchmark set in June 2024.",
        "published_at": "2024-06-20",
    },
]


def _make_gateway(return_content: str) -> Any:
    """Return a mock LLMGateway whose complete() returns an LLMResult-like object."""
    from intellisource.llm.gateway._types import LLMResult

    gateway = MagicMock()
    gateway.complete = AsyncMock(
        return_value=LLMResult(content=return_content, metadata={})
    )
    return gateway


# ---------------------------------------------------------------------------
# 1. Success path: valid JSON returned by LLM
# ---------------------------------------------------------------------------


class TestLlmSummarizeSuccess:
    """LLM returns valid JSON matching DIGEST_SCHEMA."""

    async def test_returns_structured_digest_on_success(self) -> None:
        """mock gateway.complete returns valid JSON → timeline/key_points populated."""
        gateway = _make_gateway(json.dumps(_VALID_DIGEST))
        result = await llm_summarize(_CLUSTER_CONTENTS, llm_gateway=gateway)

        assert result["title"] == _VALID_DIGEST["title"]
        assert result["summary"] == _VALID_DIGEST["summary"]
        assert len(result["timeline"]) == 2
        assert result["timeline"][0]["date"] == "2024-01"
        assert result["timeline"][0]["event"] == "GPT-5 released"
        assert len(result["key_points"]) == 2
        assert "Scaling laws continue to hold" in result["key_points"]

    async def test_timeline_items_have_date_and_event_keys(self) -> None:
        """Each timeline item exposes both 'date' and 'event' keys."""
        gateway = _make_gateway(json.dumps(_VALID_DIGEST))
        result = await llm_summarize(_CLUSTER_CONTENTS, llm_gateway=gateway)

        for item in result["timeline"]:
            assert "date" in item
            assert "event" in item

    async def test_key_points_are_list_of_strings(self) -> None:
        """key_points is a list of str, not nested dicts."""
        gateway = _make_gateway(json.dumps(_VALID_DIGEST))
        result = await llm_summarize(_CLUSTER_CONTENTS, llm_gateway=gateway)

        assert isinstance(result["key_points"], list)
        for kp in result["key_points"]:
            assert isinstance(kp, str)


# ---------------------------------------------------------------------------
# 2. Fallback: LLM raises exception
# ---------------------------------------------------------------------------


class TestLlmSummarizeFallbackOnLlmError:
    """LLM raises exception → fallback to truncate_summary."""

    async def test_falls_back_to_truncate_on_llm_error(self) -> None:
        """gateway.complete raises → fallback; shape matches truncate_summary."""
        gateway = MagicMock()
        gateway.complete = AsyncMock(side_effect=RuntimeError("LLM unavailable"))

        result = await llm_summarize(_CLUSTER_CONTENTS, llm_gateway=gateway)
        expected = await truncate_summary(_CLUSTER_CONTENTS)

        assert result["title"] == expected["title"]
        assert result["summary"] == expected["summary"]
        assert result["timeline"] == []
        assert result["key_points"] == []

    async def test_logs_warning_on_llm_error(self) -> None:
        """A warning is logged when gateway.complete raises."""
        gateway = MagicMock()
        gateway.complete = AsyncMock(side_effect=ValueError("bad call"))

        with patch("intellisource.pipeline.processors.tools.logger") as mock_logger:
            await llm_summarize(_CLUSTER_CONTENTS, llm_gateway=gateway)
            mock_logger.warning.assert_called_once()


# ---------------------------------------------------------------------------
# 3. Fallback: LLM returns invalid JSON
# ---------------------------------------------------------------------------


class TestLlmSummarizeFallbackOnInvalidJson:
    """LLM returns non-JSON text → fallback."""

    async def test_falls_back_on_invalid_json(self) -> None:
        """Non-JSON response from LLM triggers fallback."""
        gateway = _make_gateway("This is not valid JSON at all.")
        result = await llm_summarize(_CLUSTER_CONTENTS, llm_gateway=gateway)

        assert result["timeline"] == []
        assert result["key_points"] == []
        assert result["title"] == _CLUSTER_CONTENTS[0]["title"]

    async def test_logs_warning_on_invalid_json(self) -> None:
        """Warning is logged when JSON parsing fails."""
        gateway = _make_gateway("not json {{ ]}")

        with patch("intellisource.pipeline.processors.tools.logger") as mock_logger:
            await llm_summarize(_CLUSTER_CONTENTS, llm_gateway=gateway)
            mock_logger.warning.assert_called_once()


# ---------------------------------------------------------------------------
# 4. Fallback: LLM returns valid JSON but violates schema
# ---------------------------------------------------------------------------


class TestLlmSummarizeFallbackOnSchemaViolation:
    """LLM returns JSON missing required fields → fallback."""

    async def test_falls_back_on_missing_timeline_field(self) -> None:
        """JSON without 'timeline' key fails schema validation → fallback."""
        bad_digest = {
            "title": "No Timeline",
            "summary": "A summary.",
            # 'timeline' is missing
            "key_points": ["point one"],
        }
        gateway = _make_gateway(json.dumps(bad_digest))
        result = await llm_summarize(_CLUSTER_CONTENTS, llm_gateway=gateway)

        # Must have fallen back: key_points from truncate_summary is []
        assert result["key_points"] == []

    async def test_falls_back_on_wrong_timeline_item_type(self) -> None:
        """timeline items must be objects with date+event; plain strings → fallback."""
        bad_digest = {
            "title": "T",
            "summary": "S",
            "timeline": ["2024-01: event"],  # strings instead of objects
            "key_points": [],
        }
        gateway = _make_gateway(json.dumps(bad_digest))
        result = await llm_summarize(_CLUSTER_CONTENTS, llm_gateway=gateway)

        assert result["timeline"] == []

    async def test_logs_warning_on_schema_violation(self) -> None:
        """Warning is logged when schema validation fails."""
        bad_digest = {"title": "T", "summary": "S"}
        gateway = _make_gateway(json.dumps(bad_digest))

        with patch("intellisource.pipeline.processors.tools.logger") as mock_logger:
            await llm_summarize(_CLUSTER_CONTENTS, llm_gateway=gateway)
            mock_logger.warning.assert_called_once()


# ---------------------------------------------------------------------------
# 5. Empty cluster_contents
# ---------------------------------------------------------------------------


class TestLlmSummarizeEmptyCluster:
    """Empty cluster_contents → no LLM call + truncate_summary fallback."""

    async def test_empty_cluster_does_not_call_llm(self) -> None:
        """Empty list → gateway.complete is never invoked."""
        gateway = MagicMock()
        gateway.complete = AsyncMock()

        result = await llm_summarize([], llm_gateway=gateway)

        gateway.complete.assert_not_called()
        assert result["title"] == ""
        assert result["summary"] == ""
        assert result["timeline"] == []
        assert result["key_points"] == []

    async def test_empty_cluster_returns_truncate_summary_shape(self) -> None:
        """Return value for empty list matches truncate_summary([]) exactly."""
        gateway = MagicMock()
        gateway.complete = AsyncMock()

        result = await llm_summarize([], llm_gateway=gateway)
        expected = await truncate_summary([])

        assert result == expected


# ---------------------------------------------------------------------------
# 6. Prompt construction: all cluster titles are included
# ---------------------------------------------------------------------------


class TestLlmSummarizePromptConstruction:
    """Verify the user prompt passed to gateway.complete references all docs."""

    async def test_prompt_includes_all_cluster_titles(self) -> None:
        """All document titles from cluster_contents appear in the user prompt."""
        gateway = _make_gateway(json.dumps(_VALID_DIGEST))

        await llm_summarize(_CLUSTER_CONTENTS, llm_gateway=gateway)

        # Inspect the call; complete is called with prompt= kwarg
        call_kwargs = gateway.complete.call_args
        prompt_arg: str = call_kwargs.kwargs.get("prompt") or call_kwargs.args[0]

        for doc in _CLUSTER_CONTENTS:
            assert doc["title"] in prompt_arg, (
                f"Title '{doc['title']}' not found in LLM prompt"
            )

    async def test_prompt_includes_system_prompt_kwarg(self) -> None:
        """gateway.complete is called with a system_prompt kwarg."""
        gateway = _make_gateway(json.dumps(_VALID_DIGEST))

        await llm_summarize(_CLUSTER_CONTENTS, llm_gateway=gateway)

        call_kwargs = gateway.complete.call_args
        system_prompt = call_kwargs.kwargs.get("system_prompt")
        assert system_prompt is not None
        assert len(system_prompt) > 0


# ---------------------------------------------------------------------------
# 7. DIGEST_SCHEMA constant is exportable and well-formed
# ---------------------------------------------------------------------------


class TestDigestSchema:
    """DIGEST_SCHEMA constant is exported and structurally valid."""

    def test_digest_schema_is_dict(self) -> None:
        """DIGEST_SCHEMA is a plain dict (importable as module constant)."""
        assert isinstance(DIGEST_SCHEMA, dict)

    def test_digest_schema_has_required_fields(self) -> None:
        """DIGEST_SCHEMA requires title, summary, timeline, key_points."""
        required = DIGEST_SCHEMA.get("required", [])
        for field in ("title", "summary", "timeline", "key_points"):
            assert field in required, f"'{field}' missing from DIGEST_SCHEMA required"

    def test_digest_schema_timeline_items_have_date_and_event(self) -> None:
        """DIGEST_SCHEMA.timeline items schema requires date and event."""
        items_schema = DIGEST_SCHEMA["properties"]["timeline"]["items"]
        assert "date" in items_schema.get("required", [])
        assert "event" in items_schema.get("required", [])
