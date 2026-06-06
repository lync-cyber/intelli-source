"""Tests for ConfigVersionManager dual-track persistence (F-35).

DB-path tests run against a real in-memory SQLite session through the
ConfigVersionRepository, so they exercise the actual ORM persistence rather
than asserting on a mocked ``session.execute`` call shape.
"""

from __future__ import annotations

from typing import AsyncIterator

import pytest
import pytest_asyncio
import yaml
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from intellisource.config.loader import ConfigVersionManager
from intellisource.config.models import SourceConfig
from intellisource.storage.models import Base, ConfigVersion, SubscriptionConfigVersion


def _make_manager() -> ConfigVersionManager:
    return ConfigVersionManager(table_name="config_versions", config_cls=SourceConfig)


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
def sample_configs() -> list[SourceConfig]:
    return [
        SourceConfig(name="src1", type="rss", url="https://example.com/feed"),
        SourceConfig(name="src2", type="api", url="https://api.example.com/v1"),
    ]


class TestConfigVersionManagerInMemory:
    """In-memory record/rollback flow (no DB)."""

    def test_record_and_rollback_in_memory(
        self, sample_configs: list[SourceConfig]
    ) -> None:
        mgr = _make_manager()
        mgr.record_version(sample_configs)
        assert mgr.current_version == 1
        result = mgr.rollback(1)
        assert [c.name for c in result] == ["src1", "src2"]  # type: ignore[attr-defined]

    def test_rollback_missing_version_raises(self) -> None:
        mgr = _make_manager()
        with pytest.raises(ValueError, match="not found"):
            mgr.rollback(99)

    def test_multiple_versions_isolated(
        self, sample_configs: list[SourceConfig]
    ) -> None:
        mgr = _make_manager()
        mgr.record_version(sample_configs[:1])
        mgr.record_version(sample_configs)
        assert mgr.current_version == 2
        v1 = mgr.rollback(1)
        assert len(v1) == 1
        assert v1[0].name == "src1"  # type: ignore[attr-defined]


class TestConfigVersionManagerAsyncPersistence:
    """record_version_async writes a real row through the repository."""

    async def test_record_version_async_persists_to_db(
        self, session: AsyncSession, sample_configs: list[SourceConfig]
    ) -> None:
        mgr = _make_manager()
        label = await mgr.record_version_async(
            sample_configs, session=session, author="test"
        )

        assert label == "1"
        assert mgr.current_version == 1

        stored = await _fetch_version(session, "1")
        assert stored is not None
        assert stored.version == "1"
        assert stored.author == "test"

    async def test_record_version_async_snapshot_is_valid_yaml(
        self, session: AsyncSession, sample_configs: list[SourceConfig]
    ) -> None:
        mgr = _make_manager()
        await mgr.record_version_async(sample_configs, session=session)

        stored = await _fetch_version(session, "1")
        assert stored is not None
        raw = yaml.safe_load(stored.snapshot_yaml)
        assert isinstance(raw, list)
        assert raw[0]["name"] == "src1"

    async def test_record_version_async_duplicate_label_is_noop(
        self, session: AsyncSession, sample_configs: list[SourceConfig]
    ) -> None:
        mgr = _make_manager()
        await mgr.record_version_async(sample_configs[:1], session=session)
        # Force a second insert under the same label "1" via a fresh manager.
        from intellisource.storage.repositories.config_version import (
            ConfigVersionRepository,
        )

        repo = ConfigVersionRepository(session, "config_versions")
        await repo.insert_version(version="1", snapshot_yaml="x: 1", author=None)
        await session.commit()

        stored = await _fetch_version(session, "1")
        assert stored is not None
        # Original snapshot preserved (ON CONFLICT DO NOTHING semantics).
        assert "src1" in stored.snapshot_yaml


class TestConfigVersionManagerRollbackByLabel:
    """rollback_by_label serves from cache; falls back to DB on miss."""

    async def test_rollback_from_cache_does_not_touch_db(
        self, session: AsyncSession, sample_configs: list[SourceConfig]
    ) -> None:
        mgr = _make_manager()
        mgr.record_version(sample_configs)  # in-memory only, no DB row written

        result = await mgr.rollback_by_label("1", session=session)
        assert [c.name for c in result] == ["src1", "src2"]  # type: ignore[attr-defined]
        # No DB row exists, proving the cache path served the rollback.
        assert await _fetch_version(session, "1") is None

    async def test_rollback_from_db_when_not_in_cache(
        self, session: AsyncSession, sample_configs: list[SourceConfig]
    ) -> None:
        writer = _make_manager()
        for _ in range(4):
            writer.record_version([])  # bump to version 5 next
        await writer.record_version_async(sample_configs, session=session)

        reader = _make_manager()  # cold cache
        result = await reader.rollback_by_label("5", session=session)
        assert [c.name for c in result] == ["src1", "src2"]  # type: ignore[attr-defined]
        assert reader.current_version == 5

    async def test_rollback_db_miss_raises_value_error(
        self, session: AsyncSession
    ) -> None:
        mgr = _make_manager()
        with pytest.raises(ValueError, match="not found"):
            await mgr.rollback_by_label("99", session=session)

    async def test_rollback_non_integer_label_raises(
        self, session: AsyncSession
    ) -> None:
        mgr = _make_manager()
        with pytest.raises(ValueError, match="not found"):
            await mgr.rollback_by_label("abc", session=session)


class TestConfigVersionManagerListVersions:
    """list_versions returns per-snapshot metadata with derived config_count."""

    async def test_list_versions_metadata_and_count(
        self, session: AsyncSession, sample_configs: list[SourceConfig]
    ) -> None:
        mgr = _make_manager()
        await mgr.record_version_async(sample_configs[:1], session=session, author=None)
        await mgr.record_version_async(sample_configs, session=session, author="alice")

        out = await mgr.list_versions(session, limit=20)

        assert [v["version"] for v in out] == ["2", "1"]  # newest first
        assert out[0]["config_count"] == 2
        assert out[0]["author"] == "alice"
        assert out[1]["config_count"] == 1
        assert out[1]["author"] is None

    async def test_list_versions_orders_numerically(
        self, session: AsyncSession, sample_configs: list[SourceConfig]
    ) -> None:
        mgr = _make_manager()
        for _ in range(10):
            await mgr.record_version_async(sample_configs[:1], session=session)

        out = await mgr.list_versions(session, limit=20)
        # "10" must sort before "9" (numeric, not lexical) ordering.
        assert out[0]["version"] == "10"
        assert out[-1]["version"] == "1"


async def _fetch_version(session: AsyncSession, version: str) -> ConfigVersion | None:
    from sqlalchemy import select

    return await session.scalar(
        select(ConfigVersion).where(ConfigVersion.version == version)
    )
