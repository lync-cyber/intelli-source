"""ContentDigest SSOT schema + parse_digest + dead-duplicate removal.

Pins the single source of truth for the digest result shape
({title, summary, timeline, key_points}) that is produced by summarization
and persisted into ProcessedContent.structured_data, and guards against the
re-introduction of the dead agent-layer summarizer duplicate.
"""

from __future__ import annotations

import importlib

import pytest


class TestContentDigestSchema:
    def test_content_digest_fields_and_dump_shape(self) -> None:
        from intellisource.pipeline.digest.schemas import (  # noqa: PLC0415
            ContentDigest,
            TimelineEntry,
        )

        digest = ContentDigest(
            title="T",
            summary="S",
            timeline=[TimelineEntry(date="2026-01-01", event="Launch")],
            key_points=["a", "b"],
        )
        assert digest.model_dump() == {
            "title": "T",
            "summary": "S",
            "timeline": [{"date": "2026-01-01", "event": "Launch"}],
            "key_points": ["a", "b"],
        }

    def test_content_digest_defaults_empty_collections(self) -> None:
        from intellisource.pipeline.digest.schemas import ContentDigest  # noqa: PLC0415

        assert ContentDigest(title="", summary="").model_dump() == {
            "title": "",
            "summary": "",
            "timeline": [],
            "key_points": [],
        }

    def test_content_digest_requires_title_and_summary(self) -> None:
        from pydantic import ValidationError  # noqa: PLC0415

        from intellisource.pipeline.digest.schemas import ContentDigest  # noqa: PLC0415

        with pytest.raises(ValidationError):
            ContentDigest(title="only title")  # type: ignore[call-arg]


class TestParseDigest:
    def test_parse_valid_returns_content_digest(self) -> None:
        from intellisource.pipeline.digest.schemas import (  # noqa: PLC0415
            ContentDigest,
            parse_digest,
        )

        result = parse_digest(
            {
                "title": "T",
                "summary": "S",
                "timeline": [{"date": "d", "event": "e"}],
                "key_points": ["p"],
            }
        )
        assert isinstance(result, ContentDigest)
        assert result.summary == "S"
        assert result.timeline[0].event == "e"
        assert result.key_points == ["p"]

    def test_parse_missing_required_key_returns_none(self) -> None:
        from intellisource.pipeline.digest.schemas import parse_digest  # noqa: PLC0415

        # Missing timeline + key_points must reject (preserves the prior
        # "all four keys required" contract so callers fall back to truncation).
        assert parse_digest({"title": "only", "summary": "s"}) is None

    def test_parse_malformed_timeline_returns_none(self) -> None:
        from intellisource.pipeline.digest.schemas import parse_digest  # noqa: PLC0415

        assert (
            parse_digest(
                {
                    "title": "t",
                    "summary": "s",
                    "timeline": [{"date": "d"}],  # missing 'event'
                    "key_points": [],
                }
            )
            is None
        )


class TestDeadDuplicateRemoved:
    def test_legacy_agent_summarizer_module_removed(self) -> None:
        """A single digest implementation lives in pipeline.processors.tools;
        the dead agent-layer duplicate must not exist."""
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("intellisource.agent.tools.summarizer")
