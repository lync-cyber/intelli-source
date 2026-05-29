"""B-044: LLMSummarizer processor integrates into content-process pipeline.

Backlog: docs/BACKLOG-intellisource-v1.md §B-044.

ProcessedContent.summary is currently NULL for every row because the
content-process YAML steps are pure batch processors (HTMLParser, ContentDedup,
KeywordTagger) — none call into the LLM gateway. This task adds an
LLMSummarizer processor that reads title/body_text from the pipeline context,
invokes ``truncate_summary`` with the gateway, and writes the digest summary
back into the context so ``_process_execute`` can persist it.

Tests verify:
- LLMSummarizer class exists, subclasses BaseProcessor, and is registered.
- _build_processors_from_config injects llm_gateway into LLMSummarizer.
- LLMSummarizer.process(ctx) populates ctx["summary"] via the gateway.
- Gateway failure / missing gateway falls back to truncation (no crash).
- content-process.yaml includes the new step (config drift guard).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Registry presence
# ---------------------------------------------------------------------------


class TestLLMSummarizerRegistered:
    def test_llm_summarizer_class_importable(self) -> None:
        from intellisource.pipeline.processors.summarizer import (  # noqa: PLC0415
            LLMSummarizer,
        )

        assert isinstance(LLMSummarizer, type)

    def test_llm_summarizer_subclasses_base_processor(self) -> None:
        from intellisource.pipeline.base import BaseProcessor  # noqa: PLC0415
        from intellisource.pipeline.processors.summarizer import (  # noqa: PLC0415
            LLMSummarizer,
        )

        assert issubclass(LLMSummarizer, BaseProcessor)

    def test_llm_summarizer_in_processor_registry(self) -> None:
        from intellisource.pipeline.processors.summarizer import (  # noqa: PLC0415
            LLMSummarizer,
        )
        from intellisource.pipeline.registry import PROCESSOR_REGISTRY  # noqa: PLC0415

        assert "LLMSummarizer" in PROCESSOR_REGISTRY
        assert PROCESSOR_REGISTRY["LLMSummarizer"] is LLMSummarizer


# ---------------------------------------------------------------------------
# Process behavior
# ---------------------------------------------------------------------------


def _make_complete_result(summary_json: str) -> MagicMock:
    """LLMResult shape: .content and .metadata."""
    result = MagicMock()
    result.content = summary_json
    result.metadata = {"input_tokens": 50, "output_tokens": 30}
    return result


class TestLLMSummarizerProcess:
    def test_process_writes_summary_to_context(self) -> None:
        from intellisource.pipeline.context import PipelineContext  # noqa: PLC0415
        from intellisource.pipeline.processors.summarizer import (  # noqa: PLC0415
            LLMSummarizer,
        )

        gw = MagicMock()
        gw.complete = AsyncMock(
            return_value=_make_complete_result(
                '{"title": "T", "summary": "concise summary text",'
                ' "timeline": [], "key_points": []}'
            )
        )

        summarizer = LLMSummarizer(llm_gateway=gw)
        ctx = PipelineContext()
        ctx.set("title", "Hello world")
        ctx.set("body_text", "Some long article body text here.")

        ctx = summarizer.process(ctx)

        assert ctx.get("summary") == "concise summary text"
        gw.complete.assert_awaited_once()

    def test_process_falls_back_when_gateway_returns_invalid_json(self) -> None:
        from intellisource.pipeline.context import PipelineContext  # noqa: PLC0415
        from intellisource.pipeline.processors.summarizer import (  # noqa: PLC0415
            LLMSummarizer,
        )

        gw = MagicMock()
        gw.complete = AsyncMock(
            return_value=_make_complete_result("not valid json at all")
        )

        summarizer = LLMSummarizer(llm_gateway=gw)
        ctx = PipelineContext()
        ctx.set(
            "title",
            "Article title",
        )
        ctx.set(
            "body_text",
            "First sentence. Second sentence. Third sentence. Fourth sentence.",
        )

        ctx = summarizer.process(ctx)

        summary_val = ctx.get("summary")
        assert isinstance(summary_val, str)
        assert summary_val  # non-empty fallback
        assert summary_val != ""

    def test_process_without_gateway_falls_back_to_truncation(self) -> None:
        from intellisource.pipeline.context import PipelineContext  # noqa: PLC0415
        from intellisource.pipeline.processors.summarizer import (  # noqa: PLC0415
            LLMSummarizer,
        )

        summarizer = LLMSummarizer(llm_gateway=None)
        ctx = PipelineContext()
        ctx.set("title", "T")
        ctx.set(
            "body_text",
            "First sentence. Second sentence. Third sentence. Fourth sentence.",
        )

        ctx = summarizer.process(ctx)

        summary_val = ctx.get("summary")
        assert isinstance(summary_val, str)
        assert summary_val  # non-empty fallback text

    def test_process_swallows_gateway_exception(self) -> None:
        from intellisource.pipeline.context import PipelineContext  # noqa: PLC0415
        from intellisource.pipeline.processors.summarizer import (  # noqa: PLC0415
            LLMSummarizer,
        )

        gw = MagicMock()
        gw.complete = AsyncMock(side_effect=RuntimeError("LLM down"))

        summarizer = LLMSummarizer(llm_gateway=gw)
        ctx = PipelineContext()
        ctx.set("title", "T")
        ctx.set("body_text", "Body text.")

        ctx = summarizer.process(ctx)

        summary_val = ctx.get("summary")
        assert isinstance(summary_val, str)


# ---------------------------------------------------------------------------
# Factory wiring
# ---------------------------------------------------------------------------


class TestFactoryInjectsLLMGateway:
    def test_build_processors_injects_gateway_into_llm_summarizer(self) -> None:
        from intellisource.agent.factory import (  # noqa: PLC0415
            _build_processors_from_config,
        )
        from intellisource.agent.pipeline import PipelineConfig  # noqa: PLC0415
        from intellisource.pipeline.processors.summarizer import (  # noqa: PLC0415
            LLMSummarizer,
        )

        gw = MagicMock()
        config = PipelineConfig(
            name="t",
            mode="batch",
            steps=[{"processor": "LLMSummarizer"}],
            max_steps=5,
            on_failure="skip",
        )
        processors = _build_processors_from_config(config, llm_gateway=gw)

        assert len(processors) == 1
        assert isinstance(processors[0], LLMSummarizer)
        # Internal attribute exposed for test verification; pinning the name
        # lets us catch silent removals.
        assert processors[0]._llm_gateway is gw

    def test_build_processors_llm_summarizer_without_gateway(self) -> None:
        from intellisource.agent.factory import (  # noqa: PLC0415
            _build_processors_from_config,
        )
        from intellisource.agent.pipeline import PipelineConfig  # noqa: PLC0415
        from intellisource.pipeline.processors.summarizer import (  # noqa: PLC0415
            LLMSummarizer,
        )

        config = PipelineConfig(
            name="t",
            mode="batch",
            steps=[{"processor": "LLMSummarizer"}],
            max_steps=5,
            on_failure="skip",
        )
        # llm_gateway omitted — must still build (graceful when content-process
        # builds happen during integration tests without LLM wiring).
        processors = _build_processors_from_config(config)

        assert len(processors) == 1
        assert isinstance(processors[0], LLMSummarizer)


# ---------------------------------------------------------------------------
# YAML drift guard
# ---------------------------------------------------------------------------


class TestContentProcessYamlIncludesSummarizer:
    def test_content_process_yaml_lists_llm_summarizer_step(self) -> None:
        from pathlib import Path  # noqa: PLC0415

        import yaml  # noqa: PLC0415

        yaml_path = (
            Path(__file__).resolve().parents[3]
            / "config"
            / "pipelines"
            / "content-process.yaml"
        )
        data: dict[str, Any] = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))

        step_names: list[str] = []
        for step in data.get("steps", []):
            if isinstance(step, dict):
                step_names.append(step.get("processor") or step.get("tool") or "")

        assert "LLMSummarizer" in step_names, (
            f"content-process.yaml must include LLMSummarizer step; got {step_names}"
        )


# ---------------------------------------------------------------------------
# _process_execute persists summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_execute_persists_summary_from_context() -> None:
    """_process_execute must pass ctx['summary'] to ContentRepository.create."""
    from datetime import datetime, timezone  # noqa: PLC0415
    from uuid import uuid4  # noqa: PLC0415

    from intellisource.agent.tools.executes.process import (
        _process_execute,  # noqa: PLC0415
    )
    from intellisource.pipeline.context import PipelineContext  # noqa: PLC0415

    raw_id = uuid4()
    summary_text = "synthesized digest line"

    raw_stub = MagicMock()
    raw_stub.id = raw_id
    raw_stub.body_html = "<p>hi</p>"
    raw_stub.body_text = "hi"
    raw_stub.title = "Hello"
    raw_stub.fingerprint = "fp123"
    raw_stub.source_url = "https://example.com/x"
    raw_stub.status = "pending"
    raw_stub.processed_at = None

    processed_stub = MagicMock()
    processed_stub.id = uuid4()

    create_calls: list[dict[str, Any]] = []

    class _Repo:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def get_raw_by_id(self, _rid: Any) -> Any:
            return raw_stub

        async def get_processed_by_raw_id(self, _rid: Any) -> Any:
            return None

        async def create(self, **kwargs: Any) -> Any:
            create_calls.append(kwargs)
            return processed_stub

    class _Session:
        def __init__(self) -> None:
            self.committed = False

        async def __aenter__(self) -> "_Session":
            return self

        async def __aexit__(self, *_exc_info: Any) -> None:
            return None

        async def commit(self) -> None:
            self.committed = True

    class _SessionFactory:
        def __call__(self) -> "_Session":
            return _Session()

    def _stub_execute(ctx: PipelineContext) -> PipelineContext:
        ctx.set("summary", summary_text)
        ctx.set("tags", ["t1", "t2"])
        return ctx

    pipeline_engine = MagicMock()
    pipeline_engine.execute = _stub_execute

    tool_deps = MagicMock()
    tool_deps.session_factory = _SessionFactory()
    tool_deps.pipeline_engine = pipeline_engine

    # Patch ContentRepository symbol that _process_execute imports lazily.
    import intellisource.storage.repositories.content as content_repo_mod  # noqa: PLC0415

    real_cls = content_repo_mod.ContentRepository
    content_repo_mod.ContentRepository = _Repo  # type: ignore[assignment]
    try:
        out = await _process_execute(
            content_id=str(raw_id),
            tool_deps=tool_deps,
        )
    finally:
        content_repo_mod.ContentRepository = real_cls  # type: ignore[assignment]

    assert out["status"] == "ok", out
    assert len(create_calls) == 1, (
        f"Expected exactly one repo.create call, got {len(create_calls)}"
    )
    assert create_calls[0].get("summary") == summary_text, (
        "summary from ctx must be persisted by _process_execute"
    )
    # sanity: created_at/processed_at flow remains
    assert isinstance(create_calls[0].get("processed_at"), datetime)
    assert create_calls[0]["processed_at"].tzinfo == timezone.utc
