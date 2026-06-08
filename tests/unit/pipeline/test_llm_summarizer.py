"""LLMSummarizer processor populates ctx['summary'] from a cluster digest.

The processor calls an injected ``summarize_fn`` (bound to the LLM gateway by
agent.factory); the LLM path itself lives in
agent.tools.executes.summarize_cluster. Without an injected summarizer it falls
back to truncation. ``_process_execute`` then persists summary / structured_data.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

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
        from intellisource.core.processor import BaseProcessor  # noqa: PLC0415
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


def _digest(summary: str, **extra: Any) -> dict[str, Any]:
    """A digest dict as returned by the injected summarize_fn."""
    return {
        "title": extra.get("title", "T"),
        "summary": summary,
        "timeline": extra.get("timeline", []),
        "key_points": extra.get("key_points", []),
    }


class TestLLMSummarizerProcess:
    def test_process_writes_summary_to_context(self) -> None:
        from intellisource.core.processor import PipelineContext  # noqa: PLC0415
        from intellisource.pipeline.processors.summarizer import (  # noqa: PLC0415
            LLMSummarizer,
        )

        async def fake_summarize(cluster: list[dict[str, str]]) -> dict[str, Any]:
            assert cluster == [
                {
                    "title": "Hello world",
                    "body_text": "Some long article body text here.",
                }
            ]
            return _digest("concise summary text")

        summarizer = LLMSummarizer(summarize_fn=fake_summarize)
        ctx = PipelineContext()
        ctx.set("title", "Hello world")
        ctx.set("body_text", "Some long article body text here.")

        ctx = summarizer.process(ctx)

        assert ctx.get("summary") == "concise summary text"

    def test_process_summary_empty_when_digest_lacks_summary(self) -> None:
        from intellisource.core.processor import PipelineContext  # noqa: PLC0415
        from intellisource.pipeline.processors.summarizer import (  # noqa: PLC0415
            LLMSummarizer,
        )

        async def no_summary(cluster: list[dict[str, str]]) -> dict[str, Any]:
            return {"title": "T", "timeline": [], "key_points": []}

        summarizer = LLMSummarizer(summarize_fn=no_summary)
        ctx = PipelineContext()
        ctx.set("title", "Article title")
        ctx.set("body_text", "First. Second. Third.")

        ctx = summarizer.process(ctx)

        assert ctx.get("summary") == ""

    def test_process_without_summarizer_falls_back_to_truncation(self) -> None:
        from intellisource.core.processor import PipelineContext  # noqa: PLC0415
        from intellisource.pipeline.processors.summarizer import (  # noqa: PLC0415
            LLMSummarizer,
        )

        summarizer = LLMSummarizer(summarize_fn=None)
        ctx = PipelineContext()
        ctx.set("title", "T")
        ctx.set(
            "body_text",
            "First sentence. Second sentence. Third sentence. Fourth sentence.",
        )

        ctx = summarizer.process(ctx)

        summary_val = ctx.get("summary")
        assert isinstance(summary_val, str)
        assert summary_val  # non-empty truncation fallback

    def test_process_swallows_summarizer_exception(self) -> None:
        from intellisource.core.processor import PipelineContext  # noqa: PLC0415
        from intellisource.pipeline.processors.summarizer import (  # noqa: PLC0415
            LLMSummarizer,
        )

        async def boom(cluster: list[dict[str, str]]) -> dict[str, Any]:
            raise RuntimeError("summarizer down")

        summarizer = LLMSummarizer(summarize_fn=boom)
        ctx = PipelineContext()
        ctx.set("title", "T")
        ctx.set("body_text", "Body text.")

        ctx = summarizer.process(ctx)

        assert ctx.get("summary") == ""


# ---------------------------------------------------------------------------
# Factory wiring
# ---------------------------------------------------------------------------


class TestFactoryInjectsSummarizer:
    def test_build_processors_injects_summarizer_into_llm_summarizer(self) -> None:
        from intellisource.agent.factory import (  # noqa: PLC0415
            _build_processors_from_config,
        )
        from intellisource.config.pipeline_models import PipelineConfig  # noqa: PLC0415
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
        # Factory injects a gateway-bound summarizer callable; pinning the
        # attribute name lets us catch silent removals.
        assert callable(processors[0]._summarize_fn)

    def test_build_processors_llm_summarizer_without_gateway(self) -> None:
        from intellisource.agent.factory import (  # noqa: PLC0415
            _build_processors_from_config,
        )
        from intellisource.config.pipeline_models import PipelineConfig  # noqa: PLC0415
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
    from intellisource.core.processor import PipelineContext  # noqa: PLC0415

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


# ---------------------------------------------------------------------------
# WF-1.3: full digest flows into ctx["digest"] and persists to structured_data
# ---------------------------------------------------------------------------


class TestLLMSummarizerPopulatesDigest:
    def test_process_populates_full_digest_in_context(self) -> None:
        from intellisource.core.processor import PipelineContext  # noqa: PLC0415
        from intellisource.pipeline.processors.summarizer import (  # noqa: PLC0415
            LLMSummarizer,
        )

        async def fake_summarize(cluster: list[dict[str, str]]) -> dict[str, Any]:
            return {
                "title": "DT",
                "summary": "DS",
                "timeline": [{"date": "2026-01-01", "event": "E"}],
                "key_points": ["k1", "k2"],
            }

        summarizer = LLMSummarizer(summarize_fn=fake_summarize)
        ctx = PipelineContext()
        ctx.set("title", "Hello")
        ctx.set("body_text", "Body.")

        ctx = summarizer.process(ctx)

        # Full structured digest is exposed (not just the flattened summary),
        # so the executor can persist timeline / key_points into structured_data.
        assert ctx.get("digest") == {
            "title": "DT",
            "summary": "DS",
            "timeline": [{"date": "2026-01-01", "event": "E"}],
            "key_points": ["k1", "k2"],
        }
        # back-compat: summary still flattened for existing readers
        assert ctx.get("summary") == "DS"


@pytest.mark.asyncio
async def test_process_execute_persists_structured_data_from_digest() -> None:
    """_process_execute must persist ctx['digest'] into structured_data."""
    from uuid import uuid4  # noqa: PLC0415

    from intellisource.agent.tools.executes.process import (  # noqa: PLC0415
        _process_execute,
    )
    from intellisource.core.processor import PipelineContext  # noqa: PLC0415

    raw_id = uuid4()
    digest_payload = {
        "title": "DT",
        "summary": "DS",
        "timeline": [{"date": "2026-01-01", "event": "E"}],
        "key_points": ["k"],
    }

    raw_stub = MagicMock()
    raw_stub.id = raw_id
    raw_stub.body_html = "<p>hi</p>"
    raw_stub.body_text = "hi"
    raw_stub.title = "Hello"
    raw_stub.fingerprint = "fp"
    raw_stub.source_url = "https://example.com/x"
    raw_stub.status = "pending"
    raw_stub.processed_at = None
    raw_stub.source_id = None
    raw_stub.published_at = None
    raw_stub.created_at = None

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
        async def __aenter__(self) -> "_Session":
            return self

        async def __aexit__(self, *_exc_info: Any) -> None:
            return None

        async def commit(self) -> None:
            return None

    class _SessionFactory:
        def __call__(self) -> "_Session":
            return _Session()

    def _stub_execute(ctx: PipelineContext) -> PipelineContext:
        ctx.set("summary", "DS")
        ctx.set("digest", digest_payload)
        ctx.set("tags", [])
        return ctx

    pipeline_engine = MagicMock()
    pipeline_engine.execute = _stub_execute

    tool_deps = MagicMock()
    tool_deps.session_factory = _SessionFactory()
    tool_deps.pipeline_engine = pipeline_engine

    import intellisource.storage.repositories.content as content_repo_mod  # noqa: PLC0415

    real_cls = content_repo_mod.ContentRepository
    content_repo_mod.ContentRepository = _Repo  # type: ignore[assignment]
    try:
        out = await _process_execute(content_id=str(raw_id), tool_deps=tool_deps)
    finally:
        content_repo_mod.ContentRepository = real_cls  # type: ignore[assignment]

    assert out["status"] == "ok", out
    assert len(create_calls) == 1
    assert create_calls[0].get("structured_data") == digest_payload, (
        "ctx['digest'] must be persisted into ProcessedContent.structured_data"
    )
