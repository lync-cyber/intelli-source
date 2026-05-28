"""Tests for ConfigVersionManager dual-track persistence (F-35)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

from intellisource.config.loader import ConfigVersionManager
from intellisource.config.models import SourceConfig


def _make_manager() -> ConfigVersionManager:
    return ConfigVersionManager(table_name="config_versions", config_cls=SourceConfig)


@pytest.fixture()
def sample_configs() -> list[SourceConfig]:
    return [
        SourceConfig(name="src1", type="rss", url="https://example.com/feed"),
        SourceConfig(name="src2", type="api", url="https://api.example.com/v1"),
    ]


class TestConfigVersionManagerInMemory:
    """In-memory record/rollback flow."""

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
    """record_version_async writes to DB via the passed AsyncSession."""

    async def test_record_version_async_persists_to_db(
        self, sample_configs: list[SourceConfig]
    ) -> None:
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()

        mgr = _make_manager()
        label = await mgr.record_version_async(
            sample_configs, session=mock_session, author="test"
        )

        assert label == "1"
        assert mgr.current_version == 1
        mock_session.execute.assert_awaited_once()
        mock_session.commit.assert_awaited_once()

    async def test_record_version_async_snapshot_is_valid_yaml(
        self, sample_configs: list[SourceConfig]
    ) -> None:
        captured_params: dict = {}

        async def capture_execute(stmt: object, params: dict) -> AsyncMock:  # type: ignore[override]
            captured_params.update(params)
            return AsyncMock()

        mock_session = AsyncMock()
        mock_session.execute = capture_execute
        mock_session.commit = AsyncMock()

        mgr = _make_manager()
        await mgr.record_version_async(sample_configs, session=mock_session)

        raw = yaml.safe_load(captured_params["snapshot_yaml"])
        assert isinstance(raw, list)
        assert raw[0]["name"] == "src1"


class TestConfigVersionManagerRollbackByLabel:
    """rollback_by_label serves from cache; falls back to DB on miss."""

    async def test_rollback_from_cache_does_not_touch_db(
        self, sample_configs: list[SourceConfig]
    ) -> None:
        mgr = _make_manager()
        mgr.record_version(sample_configs)
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()  # should not be called

        result = await mgr.rollback_by_label("1", session=mock_session)
        assert [c.name for c in result] == ["src1", "src2"]  # type: ignore[attr-defined]
        mock_session.execute.assert_not_awaited()

    async def test_rollback_from_db_when_not_in_cache(
        self, sample_configs: list[SourceConfig]
    ) -> None:
        snapshot = yaml.dump([c.model_dump() for c in sample_configs])
        mock_row = MagicMock()
        mock_row.fetchone = MagicMock(return_value=(snapshot,))

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_row)

        mgr = _make_manager()
        result = await mgr.rollback_by_label("5", session=mock_session)
        assert [c.name for c in result] == ["src1", "src2"]  # type: ignore[attr-defined]
        assert mgr.current_version == 5

    async def test_rollback_db_miss_raises_value_error(self) -> None:
        mock_row = MagicMock()
        mock_row.fetchone = MagicMock(return_value=None)
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_row)

        mgr = _make_manager()
        with pytest.raises(ValueError, match="not found"):
            await mgr.rollback_by_label("99", session=mock_session)

    async def test_rollback_non_integer_label_raises(self) -> None:
        mock_session = AsyncMock()
        mgr = _make_manager()
        with pytest.raises(ValueError, match="not found"):
            await mgr.rollback_by_label("abc", session=mock_session)
