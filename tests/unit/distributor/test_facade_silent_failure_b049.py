"""B-049: facade.distribute must not report a failed channel send as 'sent'.

Backlog: docs/BACKLOG-intellisource-v1.md §B-049.

Channels swallow transport errors internally and return
``{"status": "failed", ...}`` rather than raising, so the facade's try/except
never sees the failure: it incremented ``sent`` and wrote a push record with
status='sent' even though nothing was delivered. The facade must inspect the
returned status and treat 'failed' as a skip (no sent count, no sent record).
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_session_factory(content: MagicMock, subs: list[MagicMock]) -> MagicMock:
    scalars_result = MagicMock()
    scalars_result.one_or_none = MagicMock(return_value=content)
    scalars_result.all = MagicMock(return_value=subs)

    session = MagicMock()
    session.scalars = AsyncMock(return_value=scalars_result)
    execute_result = MagicMock()
    execute_result.scalar_one_or_none = MagicMock(return_value=None)
    session.execute = AsyncMock(return_value=execute_result)
    session.commit = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()

    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)
    return factory


def _make_content_and_sub() -> tuple[MagicMock, MagicMock]:
    cid = uuid.uuid4()
    content = MagicMock()
    content.id = cid
    content.title = "Title"
    content.body_text = "body"
    content.tags = []

    sub = MagicMock()
    sub.id = uuid.uuid4()
    sub.status = "active"
    sub.channel = "email"
    sub.channel_config = {"to_addr": "user@example.com"}
    sub.match_rules = {"keywords": ["Title"]}
    sub.frequency = "realtime"
    sub.quiet_hours = None
    return content, sub


def _build_facade(channel: AsyncMock, content: MagicMock, sub: MagicMock) -> Any:
    from intellisource.distributor.facade import DistributorFacade
    from intellisource.distributor.matcher import SubscriptionMatcher

    matcher = MagicMock(spec=SubscriptionMatcher)
    matcher.match.return_value = [sub]
    return DistributorFacade(
        session_factory=_make_session_factory(content, [sub]),
        matcher=matcher,
        channels={"email": channel},
    )


@pytest.mark.asyncio
async def test_failed_status_not_counted_as_sent() -> None:
    content, sub = _make_content_and_sub()
    channel = AsyncMock()
    channel.distribute = AsyncMock(
        return_value={"status": "failed", "error": "smtp down"}
    )
    facade = _build_facade(channel, content, sub)

    result = await facade.distribute(
        content_id=str(content.id), subscription_id=str(sub.id)
    )

    assert result["sent"] == 0, "a failed channel send must not count as sent"
    assert result["skipped"] == 1


@pytest.mark.asyncio
async def test_failed_status_does_not_write_sent_push_record() -> None:
    content, sub = _make_content_and_sub()
    channel = AsyncMock()
    channel.distribute = AsyncMock(return_value={"status": "failed", "error": "x"})
    facade = _build_facade(channel, content, sub)

    with patch.object(facade, "_record_push", new=AsyncMock()) as mock_record:
        await facade.distribute(content_id=str(content.id), subscription_id=str(sub.id))

    mock_record.assert_not_called()


@pytest.mark.asyncio
async def test_failed_status_records_failed_outcome_metric() -> None:
    content, sub = _make_content_and_sub()
    channel = AsyncMock()
    channel.distribute = AsyncMock(return_value={"status": "failed"})
    facade = _build_facade(channel, content, sub)

    with patch("intellisource.distributor.facade._record_push_outcome") as mock_outcome:
        await facade.distribute(content_id=str(content.id), subscription_id=str(sub.id))

    outcomes = [call.args[0] for call in mock_outcome.call_args_list]
    assert "failed" in outcomes
    assert "sent" not in outcomes


@pytest.mark.asyncio
async def test_success_status_still_counted_sent() -> None:
    content, sub = _make_content_and_sub()
    channel = AsyncMock()
    channel.distribute = AsyncMock(return_value={"status": "sent"})
    facade = _build_facade(channel, content, sub)

    with patch.object(facade, "_record_push", new=AsyncMock()) as mock_record:
        result = await facade.distribute(
            content_id=str(content.id), subscription_id=str(sub.id)
        )

    assert result["sent"] == 1
    mock_record.assert_called_once()


@pytest.mark.asyncio
async def test_wechat_success_vocab_counted_sent() -> None:
    content, sub = _make_content_and_sub()
    channel = AsyncMock()
    channel.distribute = AsyncMock(return_value={"status": "success"})
    facade = _build_facade(channel, content, sub)

    result = await facade.distribute(
        content_id=str(content.id), subscription_id=str(sub.id)
    )

    assert result["sent"] == 1
    assert result["skipped"] == 0
