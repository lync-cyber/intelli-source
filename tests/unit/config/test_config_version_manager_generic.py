"""Tests for ConfigVersionManager generalized over SubscriptionConfig."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

from intellisource.config.loader import ConfigVersionManager
from intellisource.config.subscription_models import SubscriptionConfig


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


class TestSubscriptionFlavoredManager:
    def test_record_and_rollback_in_memory(
        self, sample_subs: list[SubscriptionConfig]
    ) -> None:
        mgr = _make_manager()
        mgr.record_version(sample_subs)
        result = mgr.rollback(1)
        # 返回的对象必须是 SubscriptionConfig 实例（不是 BaseModel 抽象）
        assert all(isinstance(c, SubscriptionConfig) for c in result)
        names = [c.name for c in result]  # type: ignore[attr-defined]
        assert names == ["sub-a", "sub-b"]

    async def test_record_version_async_uses_subscription_table(
        self, sample_subs: list[SubscriptionConfig]
    ) -> None:
        captured_sql: list[str] = []
        captured_params: list[dict] = []

        async def capture_execute(stmt: object, params: dict) -> AsyncMock:
            captured_sql.append(str(stmt))
            captured_params.append(params)
            return AsyncMock()

        mock_session = AsyncMock()
        mock_session.execute = capture_execute
        mock_session.commit = AsyncMock()

        mgr = _make_manager()
        label = await mgr.record_version_async(sample_subs, session=mock_session)

        assert label == "1"
        # 表名落到 SQL 上
        assert "subscription_config_versions" in captured_sql[0]
        # 快照可被 yaml.safe_load 解出且保留 channel_config
        raw = yaml.safe_load(captured_params[0]["snapshot_yaml"])
        assert raw[0]["name"] == "sub-a"
        assert raw[0]["channel"] == "wework"
        assert raw[0]["channel_config"]["user_id"] == "@all"

    async def test_rollback_by_label_revives_through_subscription_config(
        self, sample_subs: list[SubscriptionConfig]
    ) -> None:
        snapshot = yaml.dump([c.model_dump() for c in sample_subs])
        mock_row = MagicMock()
        mock_row.fetchone = MagicMock(return_value=(snapshot,))
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_row)

        mgr = _make_manager()
        result = await mgr.rollback_by_label("7", session=mock_session)
        assert mgr.current_version == 7
        # 每一项都是 SubscriptionConfig 实例（而非 dict / BaseModel）
        assert all(isinstance(c, SubscriptionConfig) for c in result)
        assert [c.name for c in result] == ["sub-a", "sub-b"]  # type: ignore[attr-defined]

    async def test_rollback_select_targets_subscription_table(self) -> None:
        # Empty DB result triggers SELECT and we can inspect the SQL
        captured_sql: list[str] = []

        async def capture_execute(stmt: object, params: dict) -> MagicMock:
            captured_sql.append(str(stmt))
            row = MagicMock()
            row.fetchone = MagicMock(return_value=None)
            return row

        mock_session = AsyncMock()
        mock_session.execute = capture_execute

        mgr = _make_manager()
        with pytest.raises(ValueError, match="not found"):
            await mgr.rollback_by_label("99", session=mock_session)

        assert any("subscription_config_versions" in sql for sql in captured_sql), (
            "rollback_by_label must SELECT from subscription_config_versions"
        )
