"""Unit tests for DistributorFacade (T-097 RED phase).

Covers:
- AC-2: DistributorFacade class shape (__init__ signature + distribute method)
- AC-4: build_distributor_facade raises ValueError when required env vars missing
- AC-8: distribute() calls the 5 steps in order:
    (1) load ProcessedContent
    (2) SubscriptionMatcher.match
    (3) quiet-hours / frequency / dedup gate (hook on BaseDistributor)
    (4) channel.send  (BaseDistributor.distribute)
    (5) record_push + PII mask
"""

from __future__ import annotations

import re
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# AC-2: DistributorFacade class shape
# ---------------------------------------------------------------------------


class TestDistributorFacadeClassShape:
    """AC-2: distributor/facade.py exposes DistributorFacade with the expected
    constructor and async distribute() method."""

    def test_facade_module_importable(self) -> None:
        """DistributorFacade can be imported from intellisource.distributor.facade."""
        from intellisource.distributor.facade import DistributorFacade  # noqa: F401

    def test_facade_has_distribute_coroutine(self) -> None:
        """DistributorFacade.distribute is an async method."""
        import inspect

        from intellisource.distributor.facade import DistributorFacade

        assert inspect.iscoroutinefunction(DistributorFacade.distribute), (
            "DistributorFacade.distribute must be a coroutine (async def)"
        )

    def test_facade_init_accepts_session_factory_matcher_channels(self) -> None:
        """DistributorFacade.__init__ accepts (session_factory, matcher, channels)."""
        from intellisource.distributor.facade import DistributorFacade
        from intellisource.distributor.matcher import SubscriptionMatcher

        mock_session_factory = MagicMock()
        mock_matcher = SubscriptionMatcher()
        mock_channels: dict[str, Any] = {}

        facade = DistributorFacade(
            session_factory=mock_session_factory,
            matcher=mock_matcher,
            channels=mock_channels,
        )
        assert facade is not None

    def test_distribute_signature_accepts_content_id_and_subscription_id(
        self,
    ) -> None:
        """distribute() accepts content_id and optional subscription_id."""
        import inspect

        from intellisource.distributor.facade import DistributorFacade

        sig = inspect.signature(DistributorFacade.distribute)
        params = sig.parameters
        assert "content_id" in params, (
            "distribute() must have a 'content_id' keyword parameter"
        )
        assert "subscription_id" in params, (
            "distribute() must have a 'subscription_id' keyword parameter"
        )

    def test_distribute_subscription_id_defaults_to_none(self) -> None:
        """distribute() subscription_id defaults to None."""
        import inspect

        from intellisource.distributor.facade import DistributorFacade

        sig = inspect.signature(DistributorFacade.distribute)
        sub_id_param = sig.parameters.get("subscription_id")
        assert sub_id_param is not None
        assert sub_id_param.default is None, "subscription_id must default to None"


# ---------------------------------------------------------------------------
# AC-4: build_distributor_facade env-var hardening
# ---------------------------------------------------------------------------


class TestBuildDistributorFacadeEnvGuard:
    """AC-4: build_distributor_facade reads channel credentials from env;
    missing required vars log a WARNING and soft-disable that channel."""

    def test_missing_wechat_creds_disables_wechat_channel(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """wechat channel absent from facade when IS_WECHAT_APP_ID is missing."""
        import logging

        monkeypatch.delenv("IS_WECHAT_APP_ID", raising=False)
        monkeypatch.delenv("IS_WECHAT_APP_SECRET", raising=False)
        monkeypatch.setenv("IS_SMTP_HOST", "smtp.example.com")
        monkeypatch.setenv("IS_SMTP_USER", "user@example.com")
        monkeypatch.setenv("IS_SMTP_PASSWORD", "hunter2")
        monkeypatch.setenv("IS_WEWORK_CORP_ID", "fake_corp_id")
        monkeypatch.setenv("IS_WEWORK_CORP_SECRET", "fake_corp_secret")
        monkeypatch.setenv("IS_WEWORK_AGENT_ID", "1000001")

        from intellisource.composition import build_distributor_facade

        with caplog.at_level(logging.WARNING):
            facade = build_distributor_facade(
                session_factory=MagicMock(),
                redis_client=MagicMock(),
            )

        assert "wechat" not in facade._channels
        assert any(
            "wechat" in r.message and "disabled" in r.message for r in caplog.records
        )

    def test_missing_smtp_creds_disables_email_channel(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """email channel absent from facade when SMTP env vars are missing."""
        import logging

        monkeypatch.delenv("IS_SMTP_HOST", raising=False)
        monkeypatch.delenv("IS_SMTP_USER", raising=False)
        monkeypatch.delenv("IS_SMTP_PASSWORD", raising=False)
        monkeypatch.setenv("IS_WECHAT_APP_ID", "fake_app_id")
        monkeypatch.setenv("IS_WECHAT_APP_SECRET", "fake_app_secret")
        monkeypatch.setenv("IS_WEWORK_CORP_ID", "fake_corp_id")
        monkeypatch.setenv("IS_WEWORK_CORP_SECRET", "fake_corp_secret")
        monkeypatch.setenv("IS_WEWORK_AGENT_ID", "1000001")

        from intellisource.composition import build_distributor_facade

        with caplog.at_level(logging.WARNING):
            facade = build_distributor_facade(
                session_factory=MagicMock(),
                redis_client=MagicMock(),
            )

        assert "email" not in facade._channels
        assert any(
            "email" in r.message and "disabled" in r.message for r in caplog.records
        )

    def test_all_env_present_returns_non_none_facade(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With all required env vars set build_distributor_facade returns a facade."""
        monkeypatch.setenv("IS_WECHAT_APP_ID", "fake_app_id")
        monkeypatch.setenv("IS_WECHAT_APP_SECRET", "fake_app_secret")
        monkeypatch.setenv("IS_SMTP_HOST", "smtp.example.com")
        monkeypatch.setenv("IS_SMTP_USER", "user@example.com")
        monkeypatch.setenv("IS_SMTP_PASSWORD", "hunter2")
        monkeypatch.setenv("IS_WEWORK_CORP_ID", "fake_corp_id")
        monkeypatch.setenv("IS_WEWORK_CORP_SECRET", "fake_corp_secret")
        monkeypatch.setenv("IS_WEWORK_AGENT_ID", "1000001")

        from intellisource.composition import build_distributor_facade

        facade = build_distributor_facade(
            session_factory=MagicMock(),
            redis_client=MagicMock(),
        )
        assert facade is not None
        assert hasattr(facade, "distribute"), (
            "build_distributor_facade must return an object with a .distribute() method"
        )
        assert facade._channels["wechat"]._http is not None
        assert facade._channels["wework"].http_client is not None


# ---------------------------------------------------------------------------
# AC-1: build_collector_registry registers rss / api / web
# ---------------------------------------------------------------------------


class TestBuildCollectorRegistry:
    """AC-1: build_collector_registry() returns a CollectorRegistry
    with rss, api, and web adapters registered."""

    def test_registry_has_rss(self) -> None:
        from intellisource.composition import build_collector_registry

        registry = build_collector_registry()
        collector = registry.get("rss")
        assert collector is not None, (
            "registry.get('rss') must return a non-None collector"
        )

    def test_registry_has_api(self) -> None:
        from intellisource.composition import build_collector_registry

        registry = build_collector_registry()
        collector = registry.get("api")
        assert collector is not None, (
            "registry.get('api') must return a non-None collector"
        )

    def test_registry_has_web(self) -> None:
        from intellisource.composition import build_collector_registry

        registry = build_collector_registry()
        collector = registry.get("web")
        assert collector is not None, (
            "registry.get('web') must return a non-None collector"
        )

    def test_registry_returns_collector_registry_instance(self) -> None:
        from intellisource.collector.registry import CollectorRegistry
        from intellisource.composition import build_collector_registry

        registry = build_collector_registry()
        assert isinstance(registry, CollectorRegistry)


# ---------------------------------------------------------------------------
# AC-8: distribute() 5-step ordered execution
# ---------------------------------------------------------------------------


class TestDistributeFiveSteps:
    """AC-8: DistributorFacade.distribute() executes the 5 steps in order:
    (1) load ProcessedContent from DB
    (2) SubscriptionMatcher.match
    (3) quiet_hours / frequency / dedup gate
    (4) channel.send  (BaseDistributor.distribute)
    (5) record_push + PII mask
    """

    @pytest.fixture
    def content_id(self) -> str:
        return str(uuid.uuid4())

    @pytest.fixture
    def subscription_id(self) -> str:
        return str(uuid.uuid4())

    @pytest.fixture
    def mock_processed_content(self, content_id: str) -> MagicMock:
        content = MagicMock()
        content.id = uuid.UUID(content_id)
        content.title = "Test Article"
        content.body_text = "Test body text about AI"
        content.tags = ["ai", "technology"]
        return content

    @pytest.fixture
    def mock_subscription(self, subscription_id: str) -> MagicMock:
        sub = MagicMock()
        sub.id = uuid.UUID(subscription_id)
        sub.status = "active"
        sub.channel = "email"
        sub.channel_config = {"to_addr": "user@example.com"}
        sub.match_rules = {"keywords": ["AI"]}
        sub.frequency = "realtime"
        sub.quiet_hours = None
        return sub

    def _make_mock_session_factory(
        self, mock_content: MagicMock, subscriptions: list[MagicMock]
    ) -> MagicMock:
        """Build a mock session_factory with scalars().one_or_none() (content)
        and scalars().all() (subscriptions) on the same result mock."""
        mock_scalars_result = MagicMock()
        mock_scalars_result.one_or_none = MagicMock(return_value=mock_content)
        mock_scalars_result.all = MagicMock(return_value=subscriptions)

        mock_session = MagicMock()
        mock_session.scalars = AsyncMock(return_value=mock_scalars_result)
        mock_execute_result = MagicMock()
        mock_execute_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_session.execute = AsyncMock(return_value=mock_execute_result)
        mock_session.commit = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()

        mock_session_factory = MagicMock()
        mock_session_factory.return_value.__aenter__ = AsyncMock(
            return_value=mock_session
        )
        mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)
        return mock_session_factory

    async def test_step1_loads_processed_content_from_db(
        self,
        content_id: str,
        subscription_id: str,
        mock_processed_content: MagicMock,
        mock_subscription: MagicMock,
    ) -> None:
        """Step 1: facade loads ProcessedContent by content_id before matching."""
        from intellisource.distributor.facade import DistributorFacade
        from intellisource.distributor.matcher import SubscriptionMatcher

        mock_matcher = MagicMock(spec=SubscriptionMatcher)
        mock_matcher.match.return_value = []

        mock_channel = AsyncMock()
        mock_channel.distribute = AsyncMock(return_value={"status": "sent"})

        mock_session_factory = self._make_mock_session_factory(
            mock_processed_content, []
        )
        mock_session = mock_session_factory.return_value.__aenter__.return_value

        facade = DistributorFacade(
            session_factory=mock_session_factory,
            matcher=mock_matcher,
            channels={"email": mock_channel},
        )

        await facade.distribute(content_id=content_id, subscription_id=subscription_id)

        # Content load + subscription resolve both go through scalars()
        assert mock_session.scalars.await_count >= 1
        mock_matcher.match.assert_called_once()
        passed_content = mock_matcher.match.call_args[0][0]
        assert passed_content is mock_processed_content

    async def test_step2_matcher_match_called_after_content_load(
        self,
        content_id: str,
        subscription_id: str,
        mock_processed_content: MagicMock,
        mock_subscription: MagicMock,
    ) -> None:
        """Step 2: SubscriptionMatcher.match is called with the loaded content."""
        from intellisource.distributor.facade import DistributorFacade
        from intellisource.distributor.matcher import SubscriptionMatcher

        mock_matcher = MagicMock(spec=SubscriptionMatcher)
        mock_matcher.match.return_value = [mock_subscription]

        mock_channel = AsyncMock()
        mock_channel.distribute = AsyncMock(return_value={"status": "sent"})

        mock_session_factory = self._make_mock_session_factory(
            mock_processed_content, [mock_subscription]
        )

        facade = DistributorFacade(
            session_factory=mock_session_factory,
            matcher=mock_matcher,
            channels={"email": mock_channel},
        )

        await facade.distribute(content_id=content_id, subscription_id=subscription_id)

        mock_matcher.match.assert_called_once()
        match_args = mock_matcher.match.call_args
        # First positional arg must be the loaded content
        assert match_args[0][0] is mock_processed_content or (
            match_args.args and match_args.args[0] is mock_processed_content
        ), "matcher.match must receive the loaded ProcessedContent as first argument"

    async def test_step3_gate_skips_send_when_dedup_true(
        self,
        content_id: str,
        subscription_id: str,
        mock_processed_content: MagicMock,
        mock_subscription: MagicMock,
    ) -> None:
        """Step 3: when dedup gate returns already-sent, channel.send is NOT called."""
        from intellisource.distributor.facade import DistributorFacade
        from intellisource.distributor.matcher import SubscriptionMatcher

        mock_matcher = MagicMock(spec=SubscriptionMatcher)
        mock_matcher.match.return_value = [mock_subscription]

        mock_channel = AsyncMock()
        mock_channel.distribute = AsyncMock(return_value={"status": "sent"})

        mock_session_factory = self._make_mock_session_factory(
            mock_processed_content, [mock_subscription]
        )

        facade = DistributorFacade(
            session_factory=mock_session_factory,
            matcher=mock_matcher,
            channels={"email": mock_channel},
        )

        # Patch dedup check to return True (already pushed)
        with patch.object(
            facade,
            "_is_already_pushed",
            new=AsyncMock(return_value=True),
        ):
            result = await facade.distribute(
                content_id=content_id, subscription_id=subscription_id
            )

        mock_channel.distribute.assert_not_called()
        assert result.get("skipped", 0) >= 1 or result.get("sent", 0) == 0, (
            "When dedup gate fires, channel.distribute must not be called "
            "and result must show skipped>0 or sent=0"
        )

    async def test_step4_channel_send_called_for_matched_subscription(
        self,
        content_id: str,
        subscription_id: str,
        mock_processed_content: MagicMock,
        mock_subscription: MagicMock,
    ) -> None:
        """Step 4: channel distributor.distribute() called for matched subscriptions."""
        from intellisource.distributor.facade import DistributorFacade
        from intellisource.distributor.matcher import SubscriptionMatcher

        mock_matcher = MagicMock(spec=SubscriptionMatcher)
        mock_matcher.match.return_value = [mock_subscription]

        mock_channel = AsyncMock()
        mock_channel.distribute = AsyncMock(return_value={"status": "sent"})

        mock_session_factory = self._make_mock_session_factory(
            mock_processed_content, [mock_subscription]
        )

        facade = DistributorFacade(
            session_factory=mock_session_factory,
            matcher=mock_matcher,
            channels={"email": mock_channel},
        )

        result = await facade.distribute(
            content_id=content_id, subscription_id=subscription_id
        )

        mock_channel.distribute.assert_called_once()
        assert result.get("sent", 0) >= 1, (
            "distribute() result must show sent>=1 when channel.distribute succeeds"
        )

    async def test_step5_record_push_called_after_send(
        self,
        content_id: str,
        subscription_id: str,
        mock_processed_content: MagicMock,
        mock_subscription: MagicMock,
    ) -> None:
        """Step 5: record_push is called after channel.distribute succeeds."""
        from intellisource.distributor.facade import DistributorFacade
        from intellisource.distributor.matcher import SubscriptionMatcher

        mock_matcher = MagicMock(spec=SubscriptionMatcher)
        mock_matcher.match.return_value = [mock_subscription]

        mock_channel = AsyncMock()
        mock_channel.distribute = AsyncMock(return_value={"status": "sent"})

        mock_session_factory = self._make_mock_session_factory(
            mock_processed_content, [mock_subscription]
        )

        facade = DistributorFacade(
            session_factory=mock_session_factory,
            matcher=mock_matcher,
            channels={"email": mock_channel},
        )

        with patch.object(facade, "_record_push", new=AsyncMock()) as mock_record:
            await facade.distribute(
                content_id=content_id, subscription_id=subscription_id
            )

        mock_record.assert_called_once()

    async def test_result_envelope_has_required_keys(
        self,
        content_id: str,
        subscription_id: str,
        mock_processed_content: MagicMock,
        mock_subscription: MagicMock,
    ) -> None:
        """distribute() returns dict with status/matched/sent/skipped keys."""
        from intellisource.distributor.facade import DistributorFacade
        from intellisource.distributor.matcher import SubscriptionMatcher

        mock_matcher = MagicMock(spec=SubscriptionMatcher)
        mock_matcher.match.return_value = [mock_subscription]

        mock_channel = AsyncMock()
        mock_channel.distribute = AsyncMock(return_value={"status": "sent"})

        mock_session_factory = self._make_mock_session_factory(
            mock_processed_content, [mock_subscription]
        )

        facade = DistributorFacade(
            session_factory=mock_session_factory,
            matcher=mock_matcher,
            channels={"email": mock_channel},
        )

        result = await facade.distribute(
            content_id=content_id, subscription_id=subscription_id
        )

        assert isinstance(result, dict), "distribute() must return a dict"
        for key in ("status", "matched", "sent", "skipped"):
            assert key in result, f"distribute() result must contain key '{key}'"
        assert result["status"] == "ok", "distribute() result['status'] must be 'ok'"

    async def test_no_match_returns_zero_sent(
        self,
        content_id: str,
        subscription_id: str,
        mock_processed_content: MagicMock,
    ) -> None:
        """When matcher returns no subscriptions, sent=0 and skipped=0."""
        from intellisource.distributor.facade import DistributorFacade
        from intellisource.distributor.matcher import SubscriptionMatcher

        mock_matcher = MagicMock(spec=SubscriptionMatcher)
        mock_matcher.match.return_value = []

        mock_session_factory = self._make_mock_session_factory(
            mock_processed_content, []
        )

        facade = DistributorFacade(
            session_factory=mock_session_factory,
            matcher=mock_matcher,
            channels={},
        )

        result = await facade.distribute(
            content_id=content_id, subscription_id=subscription_id
        )

        assert result["status"] == "ok"
        assert result["matched"] == 0
        assert result["sent"] == 0


# ---------------------------------------------------------------------------
# AC-8 security: PII mask applied before persistence
# ---------------------------------------------------------------------------


class TestDistributePIIMask:
    """AC-8 step 5 (security): recipient PII is masked before record_push persists."""

    async def test_pii_mask_applied_to_recipient_before_record(self) -> None:
        """The recipient email stored in push record must not contain '@'."""
        from intellisource.distributor.facade import DistributorFacade
        from intellisource.distributor.matcher import SubscriptionMatcher

        content_id = str(uuid.uuid4())
        subscription_id = str(uuid.uuid4())

        content = MagicMock()
        content.id = uuid.UUID(content_id)
        content.title = "Title"
        content.body_text = "body"
        content.tags = []

        sub = MagicMock()
        sub.id = uuid.UUID(subscription_id)
        sub.status = "active"
        sub.channel = "email"
        sub.channel_config = {"to_addr": "plaintext@example.com"}
        sub.match_rules = {"keywords": ["Title"]}
        sub.frequency = "realtime"
        sub.quiet_hours = None

        mock_matcher = MagicMock(spec=SubscriptionMatcher)
        mock_matcher.match.return_value = [sub]

        mock_channel = AsyncMock()
        mock_channel.distribute = AsyncMock(return_value={"status": "sent"})

        mock_scalars_result = MagicMock()
        mock_scalars_result.one_or_none = MagicMock(return_value=content)
        mock_scalars_result.all = MagicMock(return_value=[sub])
        mock_session = MagicMock()
        mock_session.scalars = AsyncMock(return_value=mock_scalars_result)
        mock_execute_result = MagicMock()
        mock_execute_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_session.execute = AsyncMock(return_value=mock_execute_result)
        mock_session.commit = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()
        mock_session_factory = MagicMock()
        mock_session_factory.return_value.__aenter__ = AsyncMock(
            return_value=mock_session
        )
        mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        recorded_recipient: list[str] = []

        async def _capture_record_push(*args: Any, **kwargs: Any) -> None:
            recipient = kwargs.get("recipient_id") or kwargs.get("extra_recipient", "")
            recorded_recipient.append(str(recipient))

        facade = DistributorFacade(
            session_factory=mock_session_factory,
            matcher=mock_matcher,
            channels={"email": mock_channel},
        )

        with patch.object(
            facade, "_record_push", new=AsyncMock(side_effect=_capture_record_push)
        ):
            await facade.distribute(
                content_id=content_id, subscription_id=subscription_id
            )

        if recorded_recipient:
            raw_email_re = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
            for stored in recorded_recipient:
                assert not raw_email_re.search(stored), (
                    f"PII mask must remove '@' from recipient before persistence; "
                    f"got {stored!r}"
                )


# ---------------------------------------------------------------------------
# F-27: distribute() must distinguish missing content from "no match"
# ---------------------------------------------------------------------------


class TestDistributeContentNotFound:
    """When the content row cannot be loaded, callers need a distinct signal so
    a missing content does not look the same as "0 subscriptions matched"."""

    def _empty_session_factory(self, returned_content: Any) -> MagicMock:
        mock_scalars_result = MagicMock()
        mock_scalars_result.one_or_none = MagicMock(return_value=returned_content)
        mock_scalars_result.all = MagicMock(return_value=[])

        mock_session = MagicMock()
        mock_session.scalars = AsyncMock(return_value=mock_scalars_result)
        mock_execute_result = MagicMock()
        mock_execute_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_session.execute = AsyncMock(return_value=mock_execute_result)
        mock_session.commit = AsyncMock()

        mock_session_factory = MagicMock()
        mock_session_factory.return_value.__aenter__ = AsyncMock(
            return_value=mock_session
        )
        mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)
        return mock_session_factory

    async def test_content_row_missing_returns_failed_status(self) -> None:
        """session.get returns None → distribute responds failed/content_not_found."""
        from intellisource.distributor.facade import DistributorFacade
        from intellisource.distributor.matcher import SubscriptionMatcher

        mock_matcher = MagicMock(spec=SubscriptionMatcher)
        mock_matcher.match.return_value = []

        facade = DistributorFacade(
            session_factory=self._empty_session_factory(returned_content=None),
            matcher=mock_matcher,
            channels={},
        )

        cid = str(uuid.uuid4())
        result = await facade.distribute(content_id=cid)

        assert result["status"] == "failed"
        assert result["reason"] == "content_not_found"
        assert result["content_id"] == cid
        assert result["matched"] == 0
        assert result["sent"] == 0

    async def test_invalid_content_uuid_returns_failed_status(self) -> None:
        """Non-UUID content_id is treated as content_not_found, not silently 200."""
        from intellisource.distributor.facade import DistributorFacade
        from intellisource.distributor.matcher import SubscriptionMatcher

        mock_matcher = MagicMock(spec=SubscriptionMatcher)
        mock_matcher.match.return_value = []

        facade = DistributorFacade(
            session_factory=self._empty_session_factory(returned_content=None),
            matcher=mock_matcher,
            channels={},
        )

        result = await facade.distribute(content_id="not-a-uuid")

        assert result["status"] == "failed"
        assert result["reason"] == "content_not_found"

    async def test_zero_matched_subs_still_returns_ok_status(self) -> None:
        """Regression: when content exists but no sub matches, status remains ok."""
        from intellisource.distributor.facade import DistributorFacade
        from intellisource.distributor.matcher import SubscriptionMatcher

        cid = str(uuid.uuid4())
        content = MagicMock()
        content.id = uuid.UUID(cid)

        mock_matcher = MagicMock(spec=SubscriptionMatcher)
        mock_matcher.match.return_value = []

        facade = DistributorFacade(
            session_factory=self._empty_session_factory(returned_content=content),
            matcher=mock_matcher,
            channels={},
        )

        result = await facade.distribute(content_id=cid)
        assert result["status"] == "ok"
        assert result["matched"] == 0
        assert "reason" not in result
