"""Tests for ConfigVersionManager dual-track persistence (F-35)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

from intellisource.config.loader import ConfigVersionManager
from intellisource.config.models import SourceConfig


@pytest.fixture()
def sample_configs() -> list[SourceConfig]:
    return [
        SourceConfig(name="src1", type="rss", url="https://example.com/feed"),
        SourceConfig(name="src2", type="api", url="https://api.example.com/v1"),
    ]


class TestConfigVersionManagerInMemory:
    """Existing in-memory behaviour is unchanged."""

    def test_record_and_rollback_in_memory(
        self, sample_configs: list[SourceConfig]
    ) -> None:
        mgr = ConfigVersionManager()
        mgr.record_version(sample_configs)
        assert mgr.current_version == 1
        result = mgr.rollback(1)
        assert [c.name for c in result] == ["src1", "src2"]

    def test_rollback_missing_version_raises(self) -> None:
        mgr = ConfigVersionManager()
        with pytest.raises(ValueError, match="not found"):
            mgr.rollback(99)

    def test_multiple_versions_isolated(
        self, sample_configs: list[SourceConfig]
    ) -> None:
        mgr = ConfigVersionManager()
        mgr.record_version(sample_configs[:1])
        mgr.record_version(sample_configs)
        assert mgr.current_version == 2
        v1 = mgr.rollback(1)
        assert len(v1) == 1
        assert v1[0].name == "src1"


class TestConfigVersionManagerAsyncPersistence:
    """record_version_async writes to DB when session_factory is injected."""

    @pytest.mark.asyncio
    async def test_record_version_async_persists_to_db(
        self, sample_configs: list[SourceConfig]
    ) -> None:
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()

        mock_factory = MagicMock(return_value=mock_session)

        mgr = ConfigVersionManager(session_factory=mock_factory)
        label = await mgr.record_version_async(sample_configs, author="test")

        assert label == "1"
        assert mgr.current_version == 1
        mock_session.execute.assert_awaited_once()
        mock_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_record_version_async_no_factory(
        self, sample_configs: list[SourceConfig]
    ) -> None:
        mgr = ConfigVersionManager()
        label = await mgr.record_version_async(sample_configs)
        assert label == "1"
        assert mgr.current_version == 1

    @pytest.mark.asyncio
    async def test_record_version_async_snapshot_is_valid_yaml(
        self, sample_configs: list[SourceConfig]
    ) -> None:
        captured_params: dict = {}

        async def capture_execute(stmt: object, params: dict) -> AsyncMock:  # type: ignore[override]
            captured_params.update(params)
            return AsyncMock()

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.execute = capture_execute
        mock_session.commit = AsyncMock()

        mgr = ConfigVersionManager(session_factory=MagicMock(return_value=mock_session))
        await mgr.record_version_async(sample_configs)

        raw = yaml.safe_load(captured_params["snapshot_yaml"])
        assert isinstance(raw, list)
        assert raw[0]["name"] == "src1"


class TestConfigVersionManagerRollbackByLabel:
    """rollback_by_label serves from cache; falls back to DB if needed."""

    @pytest.mark.asyncio
    async def test_rollback_from_cache(
        self, sample_configs: list[SourceConfig]
    ) -> None:
        mgr = ConfigVersionManager()
        mgr.record_version(sample_configs)
        result = await mgr.rollback_by_label("1")
        assert [c.name for c in result] == ["src1", "src2"]

    @pytest.mark.asyncio
    async def test_rollback_from_db_when_not_in_cache(
        self, sample_configs: list[SourceConfig]
    ) -> None:
        snapshot = yaml.dump([c.model_dump() for c in sample_configs])
        mock_row = MagicMock()
        mock_row.fetchone = MagicMock(return_value=(snapshot,))

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.execute = AsyncMock(return_value=mock_row)

        mgr = ConfigVersionManager(session_factory=MagicMock(return_value=mock_session))
        result = await mgr.rollback_by_label("5")
        assert [c.name for c in result] == ["src1", "src2"]
        assert mgr.current_version == 5

    @pytest.mark.asyncio
    async def test_rollback_missing_raises_value_error(self) -> None:
        mgr = ConfigVersionManager()
        with pytest.raises(ValueError, match="not found"):
            await mgr.rollback_by_label("99")

    @pytest.mark.asyncio
    async def test_rollback_non_integer_label_raises(self) -> None:
        mgr = ConfigVersionManager()
        with pytest.raises(ValueError, match="not found"):
            await mgr.rollback_by_label("abc")
