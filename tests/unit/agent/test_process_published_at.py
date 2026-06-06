"""B-046: _process_execute populates ProcessedContent.published_at.

Backlog: docs/BACKLOG-intellisource-v1.md §B-046.

The collector already parses pubDate/updated into RawContent.published_at, and
ContentRepository.create already accepts a published_at kwarg, but
``_process_execute`` never reads it from RawContent nor forwards it — so every
processed_contents row has published_at = NULL, making /search date_from/date_to
return zero results from the user's point of view.

Tests verify:
- published_at from RawContent flows through to ContentRepository.create.
- When RawContent.published_at is NULL, _process_execute falls back to
  RawContent.created_at (never persists NULL).
- A pipeline processor may override ctx["published_at"]; that value wins.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from intellisource.core.processor import PipelineContext


def _make_raw_stub(*, published_at: datetime | None, created_at: datetime) -> MagicMock:
    raw = MagicMock()
    raw.id = uuid4()
    raw.body_html = "<p>hi</p>"
    raw.body_text = "hi"
    raw.title = "Hello"
    raw.fingerprint = "fp123"
    raw.source_url = "https://example.com/x"
    raw.status = "pending"
    raw.processed_at = None
    raw.published_at = published_at
    raw.created_at = created_at
    return raw


async def _run_process_execute(
    raw_stub: MagicMock,
    ctx_overrides: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Invoke _process_execute with a fake repo/session, return create() kwargs."""
    from intellisource.agent.tools.executes.process import (  # noqa: PLC0415
        _process_execute,
    )

    create_calls: list[dict[str, Any]] = []
    processed_stub = MagicMock()
    processed_stub.id = uuid4()

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
        for key, value in (ctx_overrides or {}).items():
            ctx.set(key, value)
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
        out = await _process_execute(content_id=str(raw_stub.id), tool_deps=tool_deps)
    finally:
        content_repo_mod.ContentRepository = real_cls  # type: ignore[assignment]

    assert out["status"] == "ok", out
    return create_calls


@pytest.mark.asyncio
async def test_published_at_from_raw_is_persisted() -> None:
    pub = datetime(2024, 1, 15, 9, 30, tzinfo=timezone.utc)
    created = datetime(2024, 3, 1, 12, 0, tzinfo=timezone.utc)
    raw = _make_raw_stub(published_at=pub, created_at=created)

    create_calls = await _run_process_execute(raw)

    assert len(create_calls) == 1
    assert create_calls[0].get("published_at") == pub


@pytest.mark.asyncio
async def test_published_at_falls_back_to_created_at_when_null() -> None:
    created = datetime(2024, 3, 1, 12, 0, tzinfo=timezone.utc)
    raw = _make_raw_stub(published_at=None, created_at=created)

    create_calls = await _run_process_execute(raw)

    assert len(create_calls) == 1
    persisted = create_calls[0].get("published_at")
    assert persisted == created, (
        f"published_at must fall back to created_at (never NULL), got {persisted!r}"
    )


@pytest.mark.asyncio
async def test_ctx_published_at_override_wins() -> None:
    raw_pub = datetime(2024, 1, 15, 9, 30, tzinfo=timezone.utc)
    created = datetime(2024, 3, 1, 12, 0, tzinfo=timezone.utc)
    ctx_pub = datetime(2023, 12, 25, 0, 0, tzinfo=timezone.utc)
    raw = _make_raw_stub(published_at=raw_pub, created_at=created)

    create_calls = await _run_process_execute(
        raw, ctx_overrides={"published_at": ctx_pub}
    )

    assert len(create_calls) == 1
    assert create_calls[0].get("published_at") == ctx_pub
