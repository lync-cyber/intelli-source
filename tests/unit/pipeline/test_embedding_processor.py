"""B-045: EmbeddingProcessor populates ProcessedContent.embedding.

Backlog: docs/BACKLOG-intellisource-v1.md §B-045.

`processed_contents.embedding` is currently always NULL because no pipeline
step writes to it — `VectorStore.upsert()` is defined but never called. This
task adds an EmbeddingProcessor that reads body_text/title from the pipeline
context, asks the LLM gateway for an embedding vector, and writes it back
into the context so ``_process_execute`` can persist it.

Tests verify:
- EmbeddingProcessor class exists, subclasses BaseProcessor, registered.
- _build_processors_from_config injects llm_gateway into EmbeddingProcessor.
- EmbeddingProcessor.process(ctx) populates ctx["embedding"] via the gateway.
- Gateway failure / missing gateway leaves ctx["embedding"] as None (graceful).
- content-process.yaml includes the new step (config drift guard).
- _process_execute passes ctx["embedding"] to ContentRepository.create.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Registry presence
# ---------------------------------------------------------------------------


class TestEmbeddingProcessorRegistered:
    def test_embedder_class_importable(self) -> None:
        from intellisource.pipeline.processors.embedder import (  # noqa: PLC0415
            EmbeddingProcessor,
        )

        assert EmbeddingProcessor is not None

    def test_embedder_subclasses_base_processor(self) -> None:
        from intellisource.pipeline.base import BaseProcessor  # noqa: PLC0415
        from intellisource.pipeline.processors.embedder import (  # noqa: PLC0415
            EmbeddingProcessor,
        )

        assert issubclass(EmbeddingProcessor, BaseProcessor)

    def test_embedder_in_processor_registry(self) -> None:
        from intellisource.pipeline.processors.embedder import (  # noqa: PLC0415
            EmbeddingProcessor,
        )
        from intellisource.pipeline.registry import PROCESSOR_REGISTRY  # noqa: PLC0415

        assert "EmbeddingProcessor" in PROCESSOR_REGISTRY
        assert PROCESSOR_REGISTRY["EmbeddingProcessor"] is EmbeddingProcessor


# ---------------------------------------------------------------------------
# Process behavior
# ---------------------------------------------------------------------------


class TestEmbeddingProcessorProcess:
    def test_process_writes_embedding_to_context(self) -> None:
        from intellisource.pipeline.context import PipelineContext  # noqa: PLC0415
        from intellisource.pipeline.processors.embedder import (  # noqa: PLC0415
            EmbeddingProcessor,
        )

        vec = [0.1] * 1536
        gw = MagicMock()
        gw.embed = AsyncMock(return_value=vec)

        proc = EmbeddingProcessor(llm_gateway=gw)
        ctx = PipelineContext()
        ctx.set("title", "Hello world")
        ctx.set("body_text", "Article body to embed.")

        ctx = proc.process(ctx)

        out = ctx.get("embedding")
        assert isinstance(out, list)
        assert len(out) == 1536
        gw.embed.assert_awaited_once()

    def test_process_without_gateway_leaves_embedding_none(self) -> None:
        from intellisource.pipeline.context import PipelineContext  # noqa: PLC0415
        from intellisource.pipeline.processors.embedder import (  # noqa: PLC0415
            EmbeddingProcessor,
        )

        proc = EmbeddingProcessor(llm_gateway=None)
        ctx = PipelineContext()
        ctx.set("title", "T")
        ctx.set("body_text", "body")

        ctx = proc.process(ctx)

        assert ctx.get("embedding") is None

    def test_process_swallows_gateway_exception(self) -> None:
        from intellisource.pipeline.context import PipelineContext  # noqa: PLC0415
        from intellisource.pipeline.processors.embedder import (  # noqa: PLC0415
            EmbeddingProcessor,
        )

        gw = MagicMock()
        gw.embed = AsyncMock(side_effect=RuntimeError("embedding API down"))

        proc = EmbeddingProcessor(llm_gateway=gw)
        ctx = PipelineContext()
        ctx.set("title", "T")
        ctx.set("body_text", "Body.")

        ctx = proc.process(ctx)

        assert ctx.get("embedding") is None

    def test_process_handles_empty_body_text(self) -> None:
        from intellisource.pipeline.context import PipelineContext  # noqa: PLC0415
        from intellisource.pipeline.processors.embedder import (  # noqa: PLC0415
            EmbeddingProcessor,
        )

        gw = MagicMock()
        gw.embed = AsyncMock(return_value=[0.0] * 1536)

        proc = EmbeddingProcessor(llm_gateway=gw)
        ctx = PipelineContext()
        ctx.set("title", "")
        ctx.set("body_text", "")

        ctx = proc.process(ctx)

        assert ctx.get("embedding") is None
        gw.embed.assert_not_awaited()


# ---------------------------------------------------------------------------
# Factory wiring
# ---------------------------------------------------------------------------


class TestFactoryInjectsLLMGateway:
    def test_build_processors_injects_gateway_into_embedder(self) -> None:
        from intellisource.agent.factory import (  # noqa: PLC0415
            _build_processors_from_config,
        )
        from intellisource.agent.pipeline import PipelineConfig  # noqa: PLC0415
        from intellisource.pipeline.processors.embedder import (  # noqa: PLC0415
            EmbeddingProcessor,
        )

        gw = MagicMock()
        config = PipelineConfig(
            name="t",
            mode="batch",
            steps=[{"processor": "EmbeddingProcessor"}],
            max_steps=5,
            on_failure="skip",
        )
        processors = _build_processors_from_config(config, llm_gateway=gw)

        assert len(processors) == 1
        assert isinstance(processors[0], EmbeddingProcessor)
        assert processors[0]._llm_gateway is gw

    def test_build_processors_embedder_without_gateway(self) -> None:
        from intellisource.agent.factory import (  # noqa: PLC0415
            _build_processors_from_config,
        )
        from intellisource.agent.pipeline import PipelineConfig  # noqa: PLC0415
        from intellisource.pipeline.processors.embedder import (  # noqa: PLC0415
            EmbeddingProcessor,
        )

        config = PipelineConfig(
            name="t",
            mode="batch",
            steps=[{"processor": "EmbeddingProcessor"}],
            max_steps=5,
            on_failure="skip",
        )
        processors = _build_processors_from_config(config)

        assert len(processors) == 1
        assert isinstance(processors[0], EmbeddingProcessor)


# ---------------------------------------------------------------------------
# YAML drift guard
# ---------------------------------------------------------------------------


class TestContentProcessYamlIncludesEmbedder:
    def test_content_process_yaml_lists_embedder_step(self) -> None:
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

        assert "EmbeddingProcessor" in step_names, (
            f"content-process.yaml must include EmbeddingProcessor step; "
            f"got {step_names}"
        )


# ---------------------------------------------------------------------------
# _process_execute persists embedding
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_execute_persists_embedding_from_context() -> None:
    """_process_execute must pass ctx['embedding'] to ContentRepository.create."""
    from datetime import datetime, timezone  # noqa: PLC0415
    from uuid import uuid4  # noqa: PLC0415

    from intellisource.agent.tools.executes.process import (
        _process_execute,  # noqa: PLC0415
    )
    from intellisource.pipeline.context import PipelineContext  # noqa: PLC0415

    raw_id = uuid4()
    embedding_vec = [0.42] * 1536

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
        ctx.set("summary", "synth")
        ctx.set("tags", ["t1"])
        ctx.set("embedding", embedding_vec)
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
        out = await _process_execute(
            content_id=str(raw_id),
            tool_deps=tool_deps,
        )
    finally:
        content_repo_mod.ContentRepository = real_cls  # type: ignore[assignment]

    assert out["status"] == "ok", out
    assert len(create_calls) == 1
    assert create_calls[0].get("embedding") == embedding_vec, (
        "embedding from ctx must be persisted by _process_execute"
    )
    assert isinstance(create_calls[0].get("processed_at"), datetime)
    assert create_calls[0]["processed_at"].tzinfo == timezone.utc


@pytest.mark.asyncio
async def test_process_execute_omits_embedding_when_ctx_none() -> None:
    """When ctx['embedding'] is None, repo.create should NOT receive
    embedding=None (let DB default to NULL). Either omit the kwarg
    or pass None — accept both."""
    from uuid import uuid4  # noqa: PLC0415

    from intellisource.agent.tools.executes.process import (
        _process_execute,  # noqa: PLC0415
    )
    from intellisource.pipeline.context import PipelineContext  # noqa: PLC0415

    raw_id = uuid4()
    raw_stub = MagicMock()
    raw_stub.id = raw_id
    raw_stub.body_html = ""
    raw_stub.body_text = ""
    raw_stub.title = "T"
    raw_stub.fingerprint = "fp"
    raw_stub.source_url = "https://example.com/y"
    raw_stub.status = "pending"
    raw_stub.processed_at = None

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
            stub = MagicMock()
            stub.id = uuid4()
            return stub

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
        ctx.set("embedding", None)
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
    embedding_kwarg = create_calls[0].get("embedding")
    assert embedding_kwarg is None, (
        f"embedding must be None (DB default NULL), got {embedding_kwarg!r}"
    )
