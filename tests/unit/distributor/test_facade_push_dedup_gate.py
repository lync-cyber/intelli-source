"""Unit tests for DistributorFacade._is_already_pushed (E-05)."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from intellisource.distributor.facade import DistributorFacade
from intellisource.distributor.matcher import SubscriptionMatcher


@asynccontextmanager
async def _session_cm() -> Any:
    yield MagicMock()


class TestFacadePushDedupGate:
    @pytest.mark.asyncio
    async def test_is_already_pushed_delegates_to_push_repository(self) -> None:
        content_id = str(uuid.uuid4())
        subscription_id = str(uuid.uuid4())
        channel = "email"

        facade = DistributorFacade(
            session_factory=MagicMock(return_value=_session_cm()),
            matcher=SubscriptionMatcher(),
            channels={},
        )

        with pytest.MonkeyPatch.context() as mp:
            mock_repo = MagicMock()
            mock_repo.exists = AsyncMock(return_value=True)
            mp.setattr(
                "intellisource.storage.repositories.push.PushRepository",
                lambda session: mock_repo,
            )

            already = await facade._is_already_pushed(
                content_id=content_id,
                subscription_id=subscription_id,
                channel=channel,
            )

        assert already is True
        mock_repo.exists.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_distribute_skips_when_push_record_exists(self) -> None:
        content_id = str(uuid.uuid4())
        subscription_id = str(uuid.uuid4())

        mock_content = MagicMock()
        mock_content.id = uuid.UUID(content_id)
        mock_sub = MagicMock()
        mock_sub.id = uuid.UUID(subscription_id)
        mock_sub.status = "active"
        mock_sub.channel = "email"
        mock_sub.channel_config = {"to_addr": "user@example.com"}

        mock_session = MagicMock()
        mock_session.get = AsyncMock(return_value=mock_content)
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [mock_sub]
        mock_session.scalars = AsyncMock(return_value=mock_scalars)
        mock_execute_result = MagicMock()
        mock_execute_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_session.execute = AsyncMock(return_value=mock_execute_result)
        mock_session.commit = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()

        @asynccontextmanager
        async def session_factory() -> Any:
            yield mock_session

        mock_channel = AsyncMock()
        mock_matcher = MagicMock()
        mock_matcher.match.return_value = [mock_sub]

        facade = DistributorFacade(
            session_factory=session_factory,
            matcher=mock_matcher,
            channels={"email": mock_channel},
        )

        with pytest.MonkeyPatch.context() as mp:
            mock_repo = MagicMock()
            mock_repo.exists = AsyncMock(return_value=True)
            mp.setattr(
                "intellisource.storage.repositories.push.PushRepository",
                lambda session: mock_repo,
            )

            result = await facade.distribute(
                content_id=content_id,
                subscription_id=subscription_id,
            )

        mock_channel.distribute.assert_not_called()
        assert result["skipped"] >= 1
