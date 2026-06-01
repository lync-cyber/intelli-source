"""Tests for TopicService.enable against a real in-memory SQLite database."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from intellisource.config.subscription_validator import SubscriptionValidationError
from intellisource.storage.models import Source, Subscription
from intellisource.topic.service import TopicNotFoundError, TopicService


class TestEnableSources:
    async def test_enable_unknown_topic_raises(self, session: AsyncSession) -> None:
        svc = TopicService(session)
        with pytest.raises(TopicNotFoundError):
            await svc.enable("no-such-topic")

    async def test_enable_persists_topic_sources(self, session: AsyncSession) -> None:
        svc = TopicService(session)
        result = await svc.enable("technology", create_subscription=False)

        topic = svc.get_topic("technology")
        assert topic is not None
        assert result["sources_loaded"] == len(topic.sources)

        rows = (await session.execute(select(Source))).scalars().all()
        names = {s.name for s in rows}
        for src in topic.sources:
            assert src.name in names

    async def test_enable_discipline_topic_persists_discipline_tags(
        self, session: AsyncSession
    ) -> None:
        svc = TopicService(session)
        await svc.enable("electrical-engineering", create_subscription=False)

        rows = (await session.execute(select(Source))).scalars().all()
        assert rows, "expected sources to be created"
        for s in rows:
            assert "电气工程" in list(s.discipline_tags), (
                f"source {s.name} missing discipline tag; got {s.discipline_tags}"
            )


class TestEnableSubscription:
    async def test_enable_with_wework_creates_subscription(
        self, session: AsyncSession
    ) -> None:
        svc = TopicService(session)
        result = await svc.enable("artificial-intelligence", channel="wework")

        assert result["subscription"] is not None
        assert result["subscription"]["channel"] == "wework"

        subs = (await session.execute(select(Subscription))).scalars().all()
        assert len(subs) == 1
        assert subs[0].name == "人工智能 订阅"
        assert subs[0].match_rules.get("tags") == ["人工智能", "ai"]

    async def test_discipline_subscription_carries_discipline_match_rule(
        self, session: AsyncSession
    ) -> None:
        svc = TopicService(session)
        await svc.enable("computer-science", channel="wework")

        subs = (await session.execute(select(Subscription))).scalars().all()
        assert len(subs) == 1
        assert subs[0].match_rules.get("discipline_tags") == [
            "计算机科学",
            "computer-science",
        ]
        assert "计算机科学" in list(subs[0].discipline_tags)

    async def test_create_subscription_false_skips_subscription(
        self, session: AsyncSession
    ) -> None:
        svc = TopicService(session)
        result = await svc.enable(
            "finance", channel="wework", create_subscription=False
        )
        assert result["subscription"] is None
        subs = (await session.execute(select(Subscription))).scalars().all()
        assert subs == []

    async def test_no_channel_skips_subscription(self, session: AsyncSession) -> None:
        svc = TopicService(session)
        result = await svc.enable("finance")
        assert result["subscription"] is None

    async def test_email_channel_without_to_addr_raises(
        self, session: AsyncSession
    ) -> None:
        svc = TopicService(session)
        with pytest.raises(SubscriptionValidationError):
            await svc.enable("finance", channel="email", channel_config={})

    async def test_email_channel_with_to_addr_succeeds(
        self, session: AsyncSession
    ) -> None:
        svc = TopicService(session)
        result = await svc.enable(
            "finance",
            channel="email",
            channel_config={"to_addr": "ops@example.com"},
        )
        assert result["subscription"]["channel"] == "email"


class TestEnableIdempotent:
    async def test_enable_twice_does_not_duplicate_sources(
        self, session: AsyncSession
    ) -> None:
        svc = TopicService(session)
        await svc.enable("technology", create_subscription=False)
        await svc.enable("technology", create_subscription=False)

        rows = (await session.execute(select(Source))).scalars().all()
        names = [s.name for s in rows]
        assert len(names) == len(set(names)), f"duplicate sources: {names}"
