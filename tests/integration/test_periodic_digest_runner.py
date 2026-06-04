"""Integration: PeriodicDigestRunner against a real Postgres.

Exercises the three SQL seams that unit tests deliberately stub:
- _periodic_subscriptions: active daily/weekly only (realtime + paused excluded)
- _window_contents: created_at >= window_start (older content excluded)
- _dispatch: real PushRepository.create + SubscriptionRepository.update on commit
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from intellisource.distributor.periodic import PeriodicDigestRunner
from intellisource.storage.models import (
    ProcessedContent,
    PushRecord,
    RawContent,
    Source,
    Subscription,
)

NOW = datetime(2026, 6, 4, 12, 0, tzinfo=timezone.utc)


class _FixedClock:
    def now(self) -> datetime:
        return NOW


class _StubChannel:
    """Records send_rendered calls; never touches the network."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def send_rendered(
        self, subscription: Any, *, title: str, body: str, fmt: str
    ) -> dict[str, Any]:
        self.calls.append(
            {"sub_id": str(subscription.id), "title": title, "body": body, "fmt": fmt}
        )
        return {"status": "sent", "channel": "email"}


async def _seed(factory: async_sessionmaker[AsyncSession]) -> dict[str, uuid.UUID]:
    """Seed one source, a fresh + an old content row, and four subscriptions."""
    ids = {
        "source": uuid.uuid4(),
        "fresh_raw": uuid.uuid4(),
        "old_raw": uuid.uuid4(),
        "fresh": uuid.uuid4(),
        "old": uuid.uuid4(),
        "daily": uuid.uuid4(),
        "weekly": uuid.uuid4(),
        "realtime": uuid.uuid4(),
        "paused": uuid.uuid4(),
    }
    async with factory() as s:
        s.add(
            Source(
                id=ids["source"],
                name=f"src-{uuid.uuid4().hex[:8]}",
                type="rss",
                url="https://example.com/feed",
                tags=[],
                status="active",
                schedule_interval=3600,
                schedule_adaptive=False,
            )
        )
        for raw_id, url_tag in ((ids["fresh_raw"], "fresh"), (ids["old_raw"], "old")):
            s.add(
                RawContent(
                    id=raw_id,
                    source_id=ids["source"],
                    title=f"raw-{url_tag}",
                    body_html="<p>x</p>",
                    source_url=f"https://example.com/{url_tag}-{uuid.uuid4().hex}",
                    fingerprint=uuid.uuid4().hex,
                    raw_metadata={},
                )
            )
        # Fresh content lands inside every window; old content predates them all.
        s.add(
            ProcessedContent(
                id=ids["fresh"],
                raw_content_id=ids["fresh_raw"],
                title="AI 重大突破",
                body_text="body",
                tags=["AI"],
                source_name="HN",
                created_at=NOW - timedelta(hours=1),
            )
        )
        s.add(
            ProcessedContent(
                id=ids["old"],
                raw_content_id=ids["old_raw"],
                title="陈年旧闻",
                body_text="body",
                tags=["AI"],
                source_name="HN",
                created_at=NOW - timedelta(days=10),
            )
        )

        def _sub(
            sub_id: uuid.UUID, *, frequency: str, status: str, last: datetime | None
        ) -> Subscription:
            return Subscription(
                id=sub_id,
                name=f"sub-{sub_id.hex[:8]}",
                channel="email",
                channel_config={"to_addr": "u@example.com"},
                match_rules={"tags": ["AI"]},
                frequency=frequency,
                status=status,
                last_sent_at=last,
            )

        s.add(
            _sub(
                ids["daily"],
                frequency="daily",
                status="active",
                last=NOW - timedelta(hours=30),
            )
        )
        s.add(
            _sub(
                ids["weekly"],
                frequency="weekly",
                status="active",
                last=NOW - timedelta(days=8),
            )
        )
        s.add(_sub(ids["realtime"], frequency="realtime", status="active", last=None))
        s.add(_sub(ids["paused"], frequency="daily", status="paused", last=None))
        await s.commit()
    return ids


class TestPeriodicDigestRunnerRealDB:
    @pytest.mark.asyncio
    async def test_run_dispatches_periodic_subs_over_real_window(
        self, pg_container: str, pg_truncate: None
    ) -> None:
        engine = create_async_engine(pg_container, poolclass=NullPool)
        try:
            factory = async_sessionmaker(
                bind=engine, class_=AsyncSession, expire_on_commit=False
            )
            ids = await _seed(factory)

            channel = _StubChannel()
            runner = PeriodicDigestRunner(
                session_factory=factory,
                channels={"email": channel},
                clock=_FixedClock(),
            )

            summary = await runner.run()

            # _periodic_subscriptions: only the two active daily/weekly subs.
            assert summary["subscriptions"] == 2
            assert summary["sent"] == 2
            assert summary["skipped"] == 0
            assert summary["failed"] == 0
            assert {c["sub_id"] for c in channel.calls} == {
                str(ids["daily"]),
                str(ids["weekly"]),
            }

            async with factory() as v:
                # _dispatch: one PushRecord per (periodic sub × fresh content);
                # _window_contents excluded the 10-day-old row, so the old
                # content id never appears.
                rows = (await v.scalars(select(PushRecord))).all()
                assert len(rows) == 2
                assert {r.content_id for r in rows} == {ids["fresh"]}
                assert {r.subscription_id for r in rows} == {
                    ids["daily"],
                    ids["weekly"],
                }
                assert all(r.status == "sent" for r in rows)
                # render_mode defaults to "code" (no LLM render configured).
                assert all(r.render_mode == "code" for r in rows)

                # _dispatch advanced last_sent_at to clock-now for dispatched subs.
                for sub_id in (ids["daily"], ids["weekly"]):
                    sub = await v.get(Subscription, sub_id)
                    assert sub is not None
                    assert sub.last_sent_at == NOW

                # Excluded subs were never touched.
                realtime = await v.get(Subscription, ids["realtime"])
                paused = await v.get(Subscription, ids["paused"])
                assert realtime is not None and realtime.last_sent_at is None
                assert paused is not None and paused.last_sent_at is None

                old_pushes = (
                    await v.scalars(
                        select(func.count())
                        .select_from(PushRecord)
                        .where(PushRecord.content_id == ids["old"])
                    )
                ).one()
                assert old_pushes == 0
        finally:
            await engine.dispose()


class _StubGateway:
    """A stub LLM gateway whose complete() returns a fixed faithful body."""

    async def complete(self, *, prompt: str, **kwargs: Any) -> Any:
        # Includes the seeded item title so the faithfulness guard passes.
        return type(
            "R", (), {"content": "<p>AI 重大突破：本期最值得关注的进展。</p>"}
        )()


async def _seed_freeform(
    factory: async_sessionmaker[AsyncSession],
) -> dict[str, uuid.UUID]:
    """One source + one fresh content + one due daily sub configured llm-freeform."""
    ids = {
        "source": uuid.uuid4(),
        "raw": uuid.uuid4(),
        "content": uuid.uuid4(),
        "sub": uuid.uuid4(),
    }
    async with factory() as s:
        s.add(
            Source(
                id=ids["source"],
                name=f"src-{uuid.uuid4().hex[:8]}",
                type="rss",
                url="https://example.com/feed",
                tags=[],
                status="active",
                schedule_interval=3600,
                schedule_adaptive=False,
            )
        )
        s.add(
            RawContent(
                id=ids["raw"],
                source_id=ids["source"],
                title="raw",
                body_html="<p>x</p>",
                source_url=f"https://example.com/{uuid.uuid4().hex}",
                fingerprint=uuid.uuid4().hex,
                raw_metadata={},
            )
        )
        s.add(
            ProcessedContent(
                id=ids["content"],
                raw_content_id=ids["raw"],
                title="AI 重大突破",
                body_text="body",
                tags=["AI"],
                source_name="HN",
                created_at=NOW - timedelta(hours=1),
            )
        )
        s.add(
            Subscription(
                id=ids["sub"],
                name=f"sub-{ids['sub'].hex[:8]}",
                channel="email",
                channel_config={
                    "to_addr": "u@example.com",
                    "template_config": {"render_mode": "llm-freeform"},
                },
                match_rules={"tags": ["AI"]},
                frequency="daily",
                status="active",
                last_sent_at=NOW - timedelta(hours=30),
            )
        )
        await s.commit()
    return ids


class TestPeriodicDigestRunnerFreeform:
    @pytest.mark.asyncio
    async def test_freeform_render_flows_to_channel_and_persists_mode(
        self, pg_container: str, pg_truncate: None
    ) -> None:
        engine = create_async_engine(pg_container, poolclass=NullPool)
        try:
            factory = async_sessionmaker(
                bind=engine, class_=AsyncSession, expire_on_commit=False
            )
            ids = await _seed_freeform(factory)

            channel = _StubChannel()
            runner = PeriodicDigestRunner(
                session_factory=factory,
                channels={"email": channel},
                llm_gateway=_StubGateway(),
                clock=_FixedClock(),
            )

            summary = await runner.run()

            assert summary["sent"] == 1
            # The LLM-rendered body reached the channel (not the Jinja template).
            assert len(channel.calls) == 1
            assert "本期最值得关注的进展" in channel.calls[0]["body"]

            async with factory() as v:
                rows = (await v.scalars(select(PushRecord))).all()
                assert len(rows) == 1
                assert rows[0].content_id == ids["content"]
                assert rows[0].render_mode == "llm-freeform"
        finally:
            await engine.dispose()
