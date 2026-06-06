"""Tests for ConfigVersionManager generalized over SubscriptionConfig.

The DB-path cases run against a real in-memory SQLite session so they verify
that the manager targets the subscription_config_versions table and revives
snapshots through SubscriptionConfig — not that a particular SQL string was
emitted.
"""

from __future__ import annotations

from typing import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from intellisource.config.loader import ConfigVersionManager
from intellisource.config.subscription_models import SubscriptionConfig
from intellisource.storage.models import Base, ConfigVersion, SubscriptionConfigVersion


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """In-memory SQLite holding only the two config-version tables."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all,
            tables=[ConfigVersion.__table__, SubscriptionConfigVersion.__table__],
        )
    factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as sess:
        yield sess
    await engine.dispose()


@pytest.fixture()
def sample_subs() -> list[SubscriptionConfig]:
    return [
        SubscriptionConfig(
            name="sub-a",
            channel="wework",
            channel_config={"user_id": "@all", "msg_type": "text"},
            match_rules={"tags": ["ai"]},
        ),
        SubscriptionConfig(
            name="sub-b",
            channel="email",
            channel_config={"to_addr": "u@x.com"},
            match_rules={"tags": ["tech"]},
        ),
    ]


def _make_manager() -> ConfigVersionManager:
    return ConfigVersionManager(
        table_name="subscription_config_versions",
        config_cls=SubscriptionConfig,
    )


async def _fetch_sub_version(
    session: AsyncSession, version: str
) -> SubscriptionConfigVersion | None:
    from sqlalchemy import select

    return await session.scalar(
        select(SubscriptionConfigVersion).where(
            SubscriptionConfigVersion.version == version
        )
    )


class TestSubscriptionFlavoredManager:
    def test_record_and_rollback_in_memory(
        self, sample_subs: list[SubscriptionConfig]
    ) -> None:
        mgr = _make_manager()
        mgr.record_version(sample_subs)
        result = mgr.rollback(1)
        # The returned objects must be SubscriptionConfig instances.
        assert all(isinstance(c, SubscriptionConfig) for c in result)
        names = [c.name for c in result]  # type: ignore[attr-defined]
        assert names == ["sub-a", "sub-b"]

    async def test_record_version_async_writes_subscription_table(
        self, session: AsyncSession, sample_subs: list[SubscriptionConfig]
    ) -> None:
        import yaml
        from sqlalchemy import select

        mgr = _make_manager()
        label = await mgr.record_version_async(sample_subs, session=session)

        assert label == "1"
        stored = await _fetch_sub_version(session, "1")
        assert stored is not None, "row must land in subscription_config_versions"
        # And the config_versions table stays empty (table isolation).
        assert await session.scalar(select(ConfigVersion.id)) is None
        raw = yaml.safe_load(stored.snapshot_yaml)
        assert raw[0]["name"] == "sub-a"
        assert raw[0]["channel"] == "wework"
        assert raw[0]["channel_config"]["user_id"] == "@all"

    async def test_rollback_by_label_revives_through_subscription_config(
        self, session: AsyncSession, sample_subs: list[SubscriptionConfig]
    ) -> None:
        writer = _make_manager()
        for _ in range(6):
            writer.record_version([])  # bump so next async record is version 7
        await writer.record_version_async(sample_subs, session=session)

        reader = _make_manager()  # cold cache → DB read
        result = await reader.rollback_by_label("7", session=session)
        assert reader.current_version == 7
        assert all(isinstance(c, SubscriptionConfig) for c in result)
        assert [c.name for c in result] == ["sub-a", "sub-b"]  # type: ignore[attr-defined]

    async def test_rollback_db_miss_raises(self, session: AsyncSession) -> None:
        mgr = _make_manager()
        with pytest.raises(ValueError, match="not found"):
            await mgr.rollback_by_label("99", session=session)
