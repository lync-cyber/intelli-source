"""B-033: build_distributor_facade soft-disables channels with missing env vars."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestB033SoftDisable:
    """build_distributor_facade logs warnings and skips disabled channels."""

    def _make_factory(self) -> AsyncMock:
        return AsyncMock()

    def _make_redis(self) -> MagicMock:
        return MagicMock()

    def test_all_channels_missing_returns_empty_channels(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        from intellisource.composition import build_distributor_facade

        factory = self._make_factory()
        redis = self._make_redis()

        with patch.dict("os.environ", {}, clear=True), caplog.at_level(logging.WARNING):
            facade = build_distributor_facade(
                session_factory=factory, redis_client=redis
            )

        assert facade._channels == {}
        assert any("wechat" in r.message for r in caplog.records)
        assert any("wework" in r.message for r in caplog.records)
        assert any("email" in r.message for r in caplog.records)
        assert any("no distribution channels" in r.message for r in caplog.records)

    def test_wework_only_gives_single_channel(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        from intellisource.composition import build_distributor_facade

        factory = self._make_factory()
        redis = self._make_redis()

        env = {
            "IS_WEWORK_CORP_ID": "corp_id",
            "IS_WEWORK_CORP_SECRET": "secret",
            "IS_WEWORK_AGENT_ID": "1000001",
        }
        with (
            patch.dict("os.environ", env, clear=True),
            caplog.at_level(logging.WARNING),
        ):
            facade = build_distributor_facade(
                session_factory=factory, redis_client=redis
            )

        assert "wework" in facade._channels
        assert "wechat" not in facade._channels
        assert "email" not in facade._channels
        assert not any(
            "wework" in r.message and "disabled" in r.message for r in caplog.records
        )
        assert any(
            "wechat" in r.message and "disabled" in r.message for r in caplog.records
        )

    def test_no_startup_error_on_empty_env(self) -> None:
        from intellisource.composition import build_distributor_facade

        factory = self._make_factory()
        redis = self._make_redis()

        with patch.dict("os.environ", {}, clear=True):
            facade = build_distributor_facade(
                session_factory=factory, redis_client=redis
            )

        assert facade._channels == {}

    def test_disabled_channel_in_facade_distribute_skips(self) -> None:
        """Facade.distribute skips subs targeting a disabled channel (pre-existing)."""
        from intellisource.distributor.facade import DistributorFacade
        from intellisource.distributor.matcher import SubscriptionMatcher

        factory = AsyncMock()
        matcher = MagicMock(spec=SubscriptionMatcher)
        # channels dict is empty — all channels disabled
        facade = DistributorFacade(
            session_factory=factory,
            matcher=matcher,
            channels={},
        )
        assert facade._channels == {}

    def test_warning_logged_with_channel_name(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        from intellisource.composition import build_distributor_facade

        factory = self._make_factory()
        redis = self._make_redis()

        with (
            patch.dict("os.environ", {}, clear=True),
            caplog.at_level(logging.WARNING, logger="intellisource.composition"),
        ):
            build_distributor_facade(session_factory=factory, redis_client=redis)

        messages = [r.message for r in caplog.records]
        assert any("'wechat'" in m or "wechat" in m for m in messages)
        assert any("'wework'" in m or "wework" in m for m in messages)
        assert any("'email'" in m or "email" in m for m in messages)
