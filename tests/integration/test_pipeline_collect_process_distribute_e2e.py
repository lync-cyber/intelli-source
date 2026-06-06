"""Integration: collect → process → distribute full DB chain."""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from intellisource.agent.deps import ToolDeps
from intellisource.agent.tools import (
    _collect_execute,
    _distribute_execute,
    _process_execute,
)
from intellisource.collector.base import RawContent as CollectedRawContent
from intellisource.composition import build_collector_registry
from intellisource.distributor.facade import DistributorFacade
from intellisource.distributor.matcher import SubscriptionMatcher
from intellisource.pipeline.engine import PipelineEngine
from intellisource.pipeline.processors.parser import HTMLParser
from intellisource.storage.models import (
    ProcessedContent,
    PushRecord,
    RawContent,
    Source,
    Subscription,
)


async def _make_source(session: AsyncSession) -> Source:
    source = Source(
        id=uuid.uuid4(),
        name=f"e2e-source-{uuid.uuid4().hex[:8]}",
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


async def _make_subscription(session: AsyncSession, source: Source) -> Subscription:
    sub = Subscription(
        id=uuid.uuid4(),
        name="e2e-email-sub",
        source_id=source.id,
        channel="email",
        channel_config={"to_addr": "subscriber@example.com"},
        match_rules={"keywords": ["chain"]},
        frequency="realtime",
        quiet_hours=None,
        discipline_tags=[],
        status="active",
    )
    session.add(sub)
    await session.flush()
    return sub


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
async def test_collect_process_distribute_persists_push_record(
    pg_session: AsyncSession,
) -> None:
    """Full tool chain: RawContent + ProcessedContent + PushRecord in DB."""
    source = await _make_source(pg_session)
    sub = await _make_subscription(pg_session, source)

    collected = [
        CollectedRawContent(
            source_url="https://example.com/chain-item",
            fingerprint=uuid.uuid4().hex,
            title="Chain article headline",
            body_html="<p>chain body</p>",
            body_text="chain body text",
        )
    ]

    registry = build_collector_registry()
    mock_collector = AsyncMock()
    mock_collector.collect_with_retry = AsyncMock(return_value=collected)

    session_factory = _session_factory_from_session(pg_session)
    engine = PipelineEngine(processors=[HTMLParser()])

    mock_email = AsyncMock()
    mock_email.distribute = AsyncMock(return_value={"status": "sent"})

    facade = DistributorFacade(
        session_factory=session_factory,
        matcher=SubscriptionMatcher(),
        channels={"email": mock_email},
        llm_gateway=None,
    )

    deps = ToolDeps(
        session_factory=session_factory,
        llm_gateway=None,
        pipeline_engine=engine,
        search_engine_factory=None,
        collector_registry=registry,
        distributor=facade,
    )

    # task_id is intentionally omitted: raw_contents.collect_task_id is a FK to
    # collect_tasks(id) and we do not create a CollectTask row in this test, so
    # passing a random UUID would violate the FK. Omitting it lets repo.create_raw
    # store NULL for collect_task_id (the column is nullable).
    with patch.object(registry, "get", return_value=mock_collector):
        collect_result = await _collect_execute(
            source_id=str(source.id),
            source_type="rss",
            tool_deps=deps,
        )

    assert collect_result["status"] == "ok"
    raw_id = uuid.UUID(collect_result["raw_content_ids"][0])
    raw_row = await pg_session.get(RawContent, raw_id)
    assert raw_row is not None
    assert raw_row.id == raw_id
    assert raw_row.source_id == source.id

    process_result = await _process_execute(content_id=str(raw_id), tool_deps=deps)
    assert process_result["status"] == "ok"
    processed_id = uuid.UUID(str(process_result["results"][0]["content_id"]))

    processed = await pg_session.get(ProcessedContent, processed_id)
    assert processed is not None
    assert processed.raw_content_id == raw_id

    dist_result = await _distribute_execute(
        content_id=str(processed_id),
        subscription_id=str(sub.id),
        tool_deps=deps,
    )

    assert dist_result["status"] == "ok"
    inner = dist_result["result"]
    assert inner["sent"] == 1

    mock_email.distribute.assert_awaited_once()
    pushed_content = mock_email.distribute.call_args.args[0]
    assert getattr(pushed_content, "title", None)

    stmt = select(PushRecord).where(
        PushRecord.content_id == processed_id,
        PushRecord.subscription_id == sub.id,
        PushRecord.channel == "email",
    )
    records = list((await pg_session.scalars(stmt)).all())
    assert len(records) == 1
    assert records[0].status == "sent"
    masked = records[0].recipient_id or ""
    assert masked, "recipient_id must be persisted"
    # pii.mask_email keeps the domain (e.g. "s***@example.com"), so the @ stays
    # present by design — assert the local part was masked instead.
    assert "***" in masked, f"recipient must be masked with '***', got {masked!r}"
    assert masked != "subscriber@example.com", "recipient_id must be masked, not raw"
