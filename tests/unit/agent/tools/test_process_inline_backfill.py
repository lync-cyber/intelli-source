"""process.py inline embedding backfill for existing_processed branch.

AC-1: existing_processed.embedding is None + ctx has list[float] -> repo.update
      called with id=existing_processed.id and embedding=<list[float]>.
AC-2: existing_processed.embedding is not None -> repo.update NOT called (idempotent).
AC-3: existing_processed.embedding is None but ctx has no valid embedding ->
      repo.update NOT called; function does not raise.
AC-4: Regression — AC-2 scenario returns existing_processed unchanged (cache hit).
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

EMBEDDING_1024 = [0.1] * 1024


def _make_tool_deps(*, mock_repo: Any, ctx_embedding: Any = None) -> Any:
    """Build a minimal ToolDeps-compatible mock.

    Routes ContentRepository to mock_repo and configures pipeline_engine to
    place ctx_embedding into the pipeline context when not None.
    """
    from intellisource.core.processor import PipelineContext  # noqa: PLC0415

    def _stub_execute(ctx: PipelineContext) -> PipelineContext:
        if ctx_embedding is not None:
            ctx.set("embedding", ctx_embedding)
        return ctx

    pipeline_engine = MagicMock()
    pipeline_engine.execute = _stub_execute

    @asynccontextmanager
    async def _session_cm() -> Any:
        session = MagicMock()
        session.commit = AsyncMock()
        yield session

    tool_deps = MagicMock()
    tool_deps.session_factory = MagicMock(return_value=_session_cm())
    tool_deps.pipeline_engine = pipeline_engine
    return tool_deps


def _make_raw_stub(raw_id: uuid.UUID) -> MagicMock:
    raw = MagicMock()
    raw.id = raw_id
    raw.title = "Test Title"
    raw.body_html = "<p>body</p>"
    raw.body_text = "body text"
    raw.fingerprint = "fp-test"
    raw.source_url = "https://example.com/article"
    raw.source_id = None
    raw.published_at = None
    raw.created_at = None
    raw.status = "pending"
    raw.processed_at = None
    return raw


def _make_existing_processed(*, embedding: list[float] | None) -> MagicMock:
    obj = MagicMock()
    obj.id = uuid.uuid4()
    obj.embedding = embedding
    return obj


async def _invoke_process(
    *,
    existing_processed: MagicMock,
    ctx_embedding: Any = None,
) -> tuple[dict[str, Any], MagicMock]:
    """Run _process_execute with patched ContentRepository; return (result, repo)."""
    import intellisource.storage.repositories.content as content_repo_mod  # noqa: PLC0415
    from intellisource.agent.tools.executes.process import (  # noqa: PLC0415
        _process_execute,
    )

    raw_id = uuid.uuid4()
    raw_stub = _make_raw_stub(raw_id)

    mock_repo = MagicMock()
    mock_repo.get_raw_by_id = AsyncMock(return_value=raw_stub)
    mock_repo.get_processed_by_raw_id = AsyncMock(return_value=existing_processed)
    updated_obj = MagicMock()
    updated_obj.id = existing_processed.id
    updated_obj.embedding = (
        ctx_embedding
        if isinstance(ctx_embedding, list)
        else existing_processed.embedding
    )
    mock_repo.update = AsyncMock(return_value=updated_obj)
    mock_repo.create = AsyncMock(return_value=MagicMock(id=uuid.uuid4()))

    tool_deps = _make_tool_deps(mock_repo=mock_repo, ctx_embedding=ctx_embedding)

    real_cls = content_repo_mod.ContentRepository
    content_repo_mod.ContentRepository = MagicMock(  # type: ignore[assignment]
        return_value=mock_repo
    )
    try:
        result = await _process_execute(content_id=str(raw_id), tool_deps=tool_deps)
    finally:
        content_repo_mod.ContentRepository = real_cls  # type: ignore[assignment]

    return result, mock_repo


# ---------------------------------------------------------------------------
# AC-1: embedding IS NULL + ctx has list[float] -> update called
# ---------------------------------------------------------------------------


class TestAC1BackfillWhenEmbeddingNull:
    @pytest.mark.asyncio
    async def test_repo_update_called_with_correct_id_and_embedding(self) -> None:
        """repo.update called with existing_processed.id and embedding=list[float]."""
        existing = _make_existing_processed(embedding=None)

        result, mock_repo = await _invoke_process(
            existing_processed=existing,
            ctx_embedding=EMBEDDING_1024,
        )

        assert result["status"] == "ok", f"Expected status=ok, got: {result}"
        assert mock_repo.update.called, (
            "ContentRepository.update must be called when "
            "existing_processed.embedding is None and ctx has list[float]"
        )
        call_kwargs = mock_repo.update.call_args
        positional = call_kwargs.args
        keyword = call_kwargs.kwargs
        called_id = positional[0] if positional else keyword.get("id")
        called_embedding = keyword.get("embedding")
        assert called_id == existing.id, (
            f"update id must equal existing_processed.id={existing.id}, got {called_id}"
        )
        assert called_embedding == EMBEDDING_1024, (
            f"update embedding must equal EMBEDDING_1024, got {called_embedding!r}"
        )

    @pytest.mark.asyncio
    async def test_return_value_is_updated_object(self) -> None:
        """Return value content_id must correspond to the processed record."""
        existing = _make_existing_processed(embedding=None)

        result, _mock_repo = await _invoke_process(
            existing_processed=existing,
            ctx_embedding=EMBEDDING_1024,
        )

        assert result["status"] == "ok"
        results = result.get("results", [])
        assert len(results) == 1
        assert results[0]["content_id"] == str(existing.id), (
            f"content_id must equal existing_processed.id={existing.id}"
        )


# ---------------------------------------------------------------------------
# AC-2: embedding already set -> update NOT called (idempotent)
# ---------------------------------------------------------------------------


class TestAC2NoUpdateWhenEmbeddingAlreadySet:
    @pytest.mark.asyncio
    async def test_update_not_called_when_embedding_exists(self) -> None:
        """repo.update NOT called when existing_processed.embedding is not None."""
        existing = _make_existing_processed(embedding=EMBEDDING_1024)

        _result, mock_repo = await _invoke_process(
            existing_processed=existing,
            ctx_embedding=EMBEDDING_1024,
        )

        assert not mock_repo.update.called, (
            "ContentRepository.update must NOT be called when "
            "existing_processed.embedding is already set (idempotent guard)"
        )

    @pytest.mark.asyncio
    async def test_returns_existing_processed_when_embedding_exists(self) -> None:
        """Returns existing_processed.id unchanged when embedding already set."""
        existing = _make_existing_processed(embedding=EMBEDDING_1024)

        result, _mock_repo = await _invoke_process(
            existing_processed=existing,
            ctx_embedding=EMBEDDING_1024,
        )

        assert result["status"] == "ok"
        results = result.get("results", [])
        assert len(results) == 1
        assert results[0]["content_id"] == str(existing.id)


# ---------------------------------------------------------------------------
# AC-3: ctx has no valid embedding -> update NOT called, no raise
# ---------------------------------------------------------------------------


class TestAC3NoUpdateWhenCtxHasNoEmbedding:
    @pytest.mark.asyncio
    async def test_update_not_called_when_ctx_embedding_is_none(self) -> None:
        """repo.update NOT called when ctx.get('embedding') is None."""
        existing = _make_existing_processed(embedding=None)

        result, mock_repo = await _invoke_process(
            existing_processed=existing,
            ctx_embedding=None,
        )

        assert result["status"] == "ok", f"Expected status=ok, got: {result}"
        assert not mock_repo.update.called, (
            "ContentRepository.update must NOT be called when ctx has no"
            " valid embedding"
        )

    @pytest.mark.asyncio
    async def test_update_not_called_when_ctx_has_no_embedding_key(self) -> None:
        """repo.update NOT called when 'embedding' key absent from ctx."""
        existing = _make_existing_processed(embedding=None)

        result, mock_repo = await _invoke_process(
            existing_processed=existing,
            ctx_embedding=None,
        )

        assert not mock_repo.update.called, (
            "ContentRepository.update must NOT be called when embedding"
            " key absent from ctx"
        )
        results = result.get("results", [])
        assert len(results) == 1
        assert results[0]["content_id"] == str(existing.id)

    @pytest.mark.asyncio
    async def test_no_raise_when_ctx_embedding_is_invalid(self) -> None:
        """No exception raised when ctx.get('embedding') is not a list."""
        existing = _make_existing_processed(embedding=None)

        result, _mock_repo = await _invoke_process(
            existing_processed=existing,
            ctx_embedding=None,
        )

        assert result["status"] == "ok"


# ---------------------------------------------------------------------------
# AC-4: Regression — cache hit with embedding already set returns unchanged
# ---------------------------------------------------------------------------


class TestAC4Regression:
    @pytest.mark.asyncio
    async def test_cache_hit_returns_existing_processed_unchanged(self) -> None:
        """Cache-hit behavior preserved: returns existing_processed, no update."""
        existing = _make_existing_processed(embedding=EMBEDDING_1024)

        result, mock_repo = await _invoke_process(
            existing_processed=existing,
            ctx_embedding=EMBEDDING_1024,
        )

        assert result["status"] == "ok"
        assert not mock_repo.update.called, (
            "update must NOT be called for cache-hit with existing"
            " embedding (regression)"
        )
        assert not mock_repo.create.called, (
            "create must NOT be called when existing_processed found (regression)"
        )
        results = result.get("results", [])
        assert len(results) == 1
        assert results[0]["content_id"] == str(existing.id), (
            "content_id must equal existing_processed.id (regression)"
        )

    @pytest.mark.asyncio
    async def test_cache_hit_embedding_null_no_ctx_no_update_no_raise(self) -> None:
        """Cache hit with NULL embedding and no ctx embedding: no update, no raise."""
        existing = _make_existing_processed(embedding=None)

        result, mock_repo = await _invoke_process(
            existing_processed=existing,
            ctx_embedding=None,
        )

        assert result["status"] == "ok"
        assert not mock_repo.update.called
        assert not mock_repo.create.called


# ---------------------------------------------------------------------------
# Wrong-dimension embedding must NOT be written (inline backfill path)
# ---------------------------------------------------------------------------


class TestR004WrongDimensionNotBackfilled:
    """Inline backfill must validate len(embedding) == EMBEDDING_DIM."""

    @pytest.mark.asyncio
    async def test_wrong_dim_embedding_not_written(self) -> None:
        """repo.update must NOT be called when ctx embedding has wrong dimension."""
        from intellisource.storage.models import EMBEDDING_DIM

        wrong_dim_embedding = [0.5] * (EMBEDDING_DIM // 2)  # 512 instead of 1024
        existing = _make_existing_processed(embedding=None)

        result, mock_repo = await _invoke_process(
            existing_processed=existing,
            ctx_embedding=wrong_dim_embedding,
        )

        assert result["status"] == "ok", f"Expected status=ok, got: {result}"
        assert not mock_repo.update.called, (
            "ContentRepository.update must NOT be called when ctx embedding "
            f"has wrong dimension ({len(wrong_dim_embedding)} != {EMBEDDING_DIM}). "
            "Inline backfill must validate len(embedding) == EMBEDDING_DIM."
        )

    @pytest.mark.asyncio
    async def test_correct_dim_embedding_is_written(self) -> None:
        """repo.update IS called when ctx embedding has correct dimension."""
        existing = _make_existing_processed(embedding=None)

        result, mock_repo = await _invoke_process(
            existing_processed=existing,
            ctx_embedding=EMBEDDING_1024,
        )

        assert result["status"] == "ok"
        assert mock_repo.update.called, (
            "ContentRepository.update must be called when ctx embedding "
            "has the correct 1024 dimension."
        )
