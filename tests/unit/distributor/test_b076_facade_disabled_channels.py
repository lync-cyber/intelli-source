"""Tests for AC-3 (G-009): DistributorFacade.distribute() disabled_channels field."""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_session_factory(content: Any, subscriptions: list[Any]) -> MagicMock:
    """Build a mock session_factory for DistributorFacade tests."""
    mock_scalars = MagicMock()
    mock_scalars.one_or_none = MagicMock(return_value=content)
    mock_scalars.all = MagicMock(return_value=subscriptions)

    mock_session = MagicMock()
    mock_session.scalars = AsyncMock(return_value=mock_scalars)
    mock_execute_result = MagicMock()
    mock_execute_result.scalar_one_or_none = MagicMock(return_value=None)
    mock_session.execute = AsyncMock(return_value=mock_execute_result)
    mock_session.commit = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()

    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)
    return factory


class TestFacadeDisabledChannels:
    """AC-3: distribute() result always contains disabled_channels list."""

    @pytest.mark.asyncio
    async def test_disabled_channels_present_when_skipped(self) -> None:
        """When a matched subscription references a missing channel adapter,
        result contains disabled_channels with that channel name."""
        from intellisource.distributor.facade import DistributorFacade
        from intellisource.distributor.matcher import SubscriptionMatcher

        content_id = str(uuid.uuid4())
        content = MagicMock()
        content.id = uuid.UUID(content_id)

        # Subscription references "wework" but facade has no wework adapter
        sub = MagicMock()
        sub.id = uuid.UUID(str(uuid.uuid4()))
        sub.channel = "wework"
        sub.channel_config = {"user_id": "user001"}

        matcher = MagicMock(spec=SubscriptionMatcher)
        matcher.match.return_value = [sub]

        facade = DistributorFacade(
            session_factory=_make_session_factory(content, [sub]),
            matcher=matcher,
            channels={},  # wework not registered
        )

        result = await facade.distribute(content_id=content_id)

        assert "disabled_channels" in result, (
            "distribute() result must contain 'disabled_channels' key"
        )
        assert "wework" in result["disabled_channels"], (
            "disabled_channels must contain 'wework'; got "
            f"{result['disabled_channels']}"
        )
        assert result["skipped"] >= 1

    @pytest.mark.asyncio
    async def test_disabled_channels_empty_when_all_configured(self) -> None:
        """When all matched channels are configured, disabled_channels is empty list."""
        from intellisource.distributor.facade import DistributorFacade
        from intellisource.distributor.matcher import SubscriptionMatcher

        content_id = str(uuid.uuid4())
        content = MagicMock()
        content.id = uuid.UUID(content_id)

        sub = MagicMock()
        sub.id = uuid.UUID(str(uuid.uuid4()))
        sub.channel = "email"
        sub.channel_config = {"to_addr": "user@example.com"}
        sub.match_rules = {}
        sub.frequency = "realtime"
        sub.quiet_hours = None

        matcher = MagicMock(spec=SubscriptionMatcher)
        matcher.match.return_value = [sub]

        mock_channel = AsyncMock()
        mock_channel.distribute = AsyncMock(return_value={"status": "sent"})

        facade = DistributorFacade(
            session_factory=_make_session_factory(content, [sub]),
            matcher=matcher,
            channels={"email": mock_channel},
        )

        with patch.object(
            facade, "_is_already_pushed", new=AsyncMock(return_value=False)
        ):
            with patch.object(facade, "_record_push", new=AsyncMock()):
                result = await facade.distribute(content_id=content_id)

        assert "disabled_channels" in result, (
            "disabled_channels key must always be present in result"
        )
        assert result["disabled_channels"] == [], (
            "disabled_channels must be [] when all channels configured; got "
            f"{result['disabled_channels']}"
        )

    @pytest.mark.asyncio
    async def test_disabled_channels_deduped(self) -> None:
        """When multiple subscriptions reference the same missing channel,
        disabled_channels contains it only once."""
        from intellisource.distributor.facade import DistributorFacade
        from intellisource.distributor.matcher import SubscriptionMatcher

        content_id = str(uuid.uuid4())
        content = MagicMock()
        content.id = uuid.UUID(content_id)

        def _make_sub(channel: str) -> MagicMock:
            sub = MagicMock()
            sub.id = uuid.UUID(str(uuid.uuid4()))
            sub.channel = channel
            sub.channel_config = {}
            return sub

        subs = [_make_sub("wework"), _make_sub("wework")]

        matcher = MagicMock(spec=SubscriptionMatcher)
        matcher.match.return_value = subs

        facade = DistributorFacade(
            session_factory=_make_session_factory(content, subs),
            matcher=matcher,
            channels={},
        )

        result = await facade.distribute(content_id=content_id)

        assert result["disabled_channels"].count("wework") == 1, (
            "disabled_channels must deduplicate channel names"
        )

    @pytest.mark.asyncio
    async def test_channel_distribute_failure_not_in_disabled_channels(self) -> None:
        """Channel distribute() returning failed does NOT count as disabled channel."""
        from intellisource.distributor.facade import DistributorFacade
        from intellisource.distributor.matcher import SubscriptionMatcher

        content_id = str(uuid.uuid4())
        content = MagicMock()
        content.id = uuid.UUID(content_id)

        sub = MagicMock()
        sub.id = uuid.UUID(str(uuid.uuid4()))
        sub.channel = "email"
        sub.channel_config = {"to_addr": "user@example.com"}
        sub.match_rules = {}
        sub.frequency = "realtime"
        sub.quiet_hours = None

        matcher = MagicMock(spec=SubscriptionMatcher)
        matcher.match.return_value = [sub]

        mock_channel = AsyncMock()
        mock_channel.distribute = AsyncMock(
            return_value={"status": "failed", "error": "SMTP error"}
        )

        facade = DistributorFacade(
            session_factory=_make_session_factory(content, [sub]),
            matcher=matcher,
            channels={"email": mock_channel},
        )

        with patch.object(
            facade, "_is_already_pushed", new=AsyncMock(return_value=False)
        ):
            with patch.object(facade, "_record_failed_push", new=AsyncMock()):
                result = await facade.distribute(content_id=content_id)

        # email was configured (adapter exists) — channel failure != disabled
        assert result["disabled_channels"] == [], (
            "channel distribute failure must not add to disabled_channels; "
            f"got {result['disabled_channels']}"
        )
