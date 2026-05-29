"""Integration tests for collect→process persistence chain (S-03/S-04)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from intellisource.agent.deps import ToolDeps
from intellisource.agent.tools import _collect_execute, _process_execute
from intellisource.collector.base import RawContent as CollectedRawContent
from intellisource.composition import build_collector_registry
from intellisource.pipeline.engine import PipelineEngine
from intellisource.pipeline.processors.parser import HTMLParser
from intellisource.storage.models import ProcessedContent, RawContent, Source


async def _make_source(session: AsyncSession) -> Source:
    source = Source(
        id=uuid.uuid4(),
        name=f"chain-source-{uuid.uuid4().hex[:8]}",
        type="rss",
        url="https://example.com/feed",
        tags=[],
        status="active",
        schedule_interval=3600,
        schedule_adaptive=False,
    )
    session.add(source)
    await session.flush()
    return source


def _session_factory_from_session(session: AsyncSession) -> Any:
    class _FakeContextManager:
        async def __aenter__(self) -> AsyncSession:
            return session

        async def __aexit__(self, *_: Any) -> None:
            pass

    def _factory() -> _FakeContextManager:
        return _FakeContextManager()

    return _factory


@pytest.mark.asyncio
async def test_collect_persists_raw_content_rows(pg_session: AsyncSession) -> None:
    source = await _make_source(pg_session)
    collected = [
        CollectedRawContent(
            source_url="https://example.com/item-1",
            fingerprint=uuid.uuid4().hex,
            title="Item 1",
            body_html="<p>one</p>",
            body_text="one",
        )
    ]

    registry = build_collector_registry()
    mock_collector = AsyncMock()
    mock_collector.collect = AsyncMock(return_value=collected)

    deps = ToolDeps(
        session_factory=_session_factory_from_session(pg_session),
        llm_gateway=None,
        pipeline_engine=None,
        search_engine_factory=None,
        collector_registry=registry,
        distributor=None,
    )

    with patch.object(registry, "get", return_value=mock_collector):
        result = await _collect_execute(
            source_id=str(source.id),
            source_type="rss",
            tool_deps=deps,
        )

    assert result["status"] == "ok"
    assert result["raw_content_ids"], "collect must persist RawContent ids"
    row = await pg_session.get(RawContent, uuid.UUID(result["raw_content_ids"][0]))
    assert row is not None
    assert row.source_id == source.id


@pytest.mark.asyncio
async def test_process_persists_processed_content(pg_session: AsyncSession) -> None:
    source = await _make_source(pg_session)
    raw = RawContent(
        id=uuid.uuid4(),
        source_id=source.id,
        title="Chain article",
        body_html="<p>Hello <b>world</b></p>",
        body_text="",
        source_url="https://example.com/article",
        fingerprint=uuid.uuid4().hex,
        raw_metadata={},
    )
    pg_session.add(raw)
    await pg_session.flush()

    engine = PipelineEngine(processors=[HTMLParser()])
    deps = ToolDeps(
        session_factory=_session_factory_from_session(pg_session),
        llm_gateway=None,
        pipeline_engine=engine,
        search_engine_factory=None,
        collector_registry=None,
        distributor=None,
    )

    result = await _process_execute(content_id=str(raw.id), tool_deps=deps)
    assert result["status"] == "ok"

    inner = result["result"]
    processed_id = uuid.UUID(str(inner["content_id"]))
    assert processed_id != raw.id

    processed = await pg_session.get(ProcessedContent, processed_id)
    assert processed is not None
    assert processed.raw_content_id == raw.id
    assert processed.body_text

    await pg_session.refresh(raw)
    assert raw.status == "processed"
    assert isinstance(raw.processed_at, datetime)

    stmt = select(ProcessedContent).where(ProcessedContent.raw_content_id == raw.id)
    rows = list((await pg_session.scalars(stmt)).all())
    assert len(rows) == 1
