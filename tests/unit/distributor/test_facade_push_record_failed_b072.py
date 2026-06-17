"""失败推送落库 — 失败路径必须写入 status='failed' 的 PushRecord。

AC1: 渠道返回 failed 状态时，_record_push 被调用且 status='failed'。
AC2: 渠道抛异常时，_record_push 被调用且 status='failed'，error_message 含异常信息。
AC3: 渠道成功时，仍写 status='sent' 记录，且 result["sent"]==1（既有行为不回归）。
AC4: 失败落库记录带与成功路径相同口径的脱敏 recipient_id。
AC5: error_message 经 PII 脱敏（email/phone 不裸露）。
AC6: 失败时 result["sent"]==0、result["skipped"] 累加、result["errors"] 仍有 reason、
     pushes_total{status="failed"} 指标仍记录。
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


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


def _make_content_and_sub(
    email: str = "user@example.com",
) -> tuple[MagicMock, MagicMock]:
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
    sub.channel_config = {"to_addr": email}
    sub.match_rules = {"keywords": ["Title"]}
    sub.frequency = "realtime"
    sub.quiet_hours = None
    return content, sub


def _build_facade(
    channel: AsyncMock,
    content: MagicMock,
    sub: MagicMock,
) -> Any:
    from intellisource.distributor.facade import DistributorFacade
    from intellisource.distributor.matcher import SubscriptionMatcher

    matcher = MagicMock(spec=SubscriptionMatcher)
    matcher.match.return_value = [sub]
    return DistributorFacade(
        session_factory=_make_session_factory(content, [sub]),
        matcher=matcher,
        channels={"email": channel},
    )


# ---------------------------------------------------------------------------
# AC1: 渠道返回 failed → _record_push 被调用且 status='failed'
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ac1_channel_failure_response_writes_failed_push_record() -> None:
    content, sub = _make_content_and_sub()
    channel = AsyncMock()
    channel.distribute = AsyncMock(
        return_value={"status": "failed", "error": "smtp down"}
    )
    facade = _build_facade(channel, content, sub)

    with patch.object(facade, "_record_push", new=AsyncMock()) as mock_record:
        await facade.distribute(content_id=str(content.id), subscription_id=str(sub.id))

    mock_record.assert_called_once()
    kwargs = mock_record.call_args.kwargs
    assert kwargs["status"] == "failed", "失败路径应写 status='failed'，绝不写 'sent'"


# ---------------------------------------------------------------------------
# AC2: 渠道抛异常 → _record_push 被调用且 status='failed'，error_message 含原因
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ac2_channel_exception_writes_failed_push_record() -> None:
    content, sub = _make_content_and_sub()
    channel = AsyncMock()
    channel.distribute = AsyncMock(side_effect=AttributeError("no attribute 'body'"))
    facade = _build_facade(channel, content, sub)

    with patch.object(facade, "_record_push", new=AsyncMock()) as mock_record:
        await facade.distribute(content_id=str(content.id), subscription_id=str(sub.id))

    mock_record.assert_called_once()
    kwargs = mock_record.call_args.kwargs
    assert kwargs["status"] == "failed"
    assert kwargs.get("error_message") is not None
    assert "body" in kwargs["error_message"]


# ---------------------------------------------------------------------------
# AC3: 渠道成功 → 仍写 status='sent'，result["sent"]==1（回归保护）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ac3_success_still_writes_sent_push_record() -> None:
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
    kwargs = mock_record.call_args.kwargs
    assert kwargs["status"] == "sent"


# ---------------------------------------------------------------------------
# AC4: 失败落库记录带脱敏 recipient_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ac4_failed_push_record_has_masked_recipient_id() -> None:
    content, sub = _make_content_and_sub(email="alice@example.com")
    channel = AsyncMock()
    channel.distribute = AsyncMock(
        return_value={"status": "failed", "error": "timeout"}
    )
    facade = _build_facade(channel, content, sub)

    with patch.object(facade, "_record_push", new=AsyncMock()) as mock_record:
        await facade.distribute(content_id=str(content.id), subscription_id=str(sub.id))

    kwargs = mock_record.call_args.kwargs
    recipient_id = kwargs.get("recipient_id")
    assert recipient_id is not None, "失败记录必须携带 recipient_id"
    # 脱敏后不得包含完整 email 本地段
    assert "alice" not in recipient_id, "recipient_id 应脱敏，不得裸露完整邮箱本地段"
    assert "@" in recipient_id or "***" in recipient_id, (
        "脱敏后的 email 应保留 '@' 结构或含 '***'"
    )


# ---------------------------------------------------------------------------
# AC5: error_message 经 PII 脱敏
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ac5_error_message_pii_masked_in_failed_push_record() -> None:
    content, sub = _make_content_and_sub()
    pii_reason = "delivery failed for bob@secret.com: smtp error"
    channel = AsyncMock()
    channel.distribute = AsyncMock(
        return_value={"status": "failed", "error": pii_reason}
    )
    facade = _build_facade(channel, content, sub)

    with patch.object(facade, "_record_push", new=AsyncMock()) as mock_record:
        await facade.distribute(content_id=str(content.id), subscription_id=str(sub.id))

    kwargs = mock_record.call_args.kwargs
    error_msg = kwargs.get("error_message", "")
    assert "bob@secret.com" not in error_msg, "error_message 不得裸露原始 email PII"
    assert error_msg is not None and len(error_msg) > 0, "error_message 不得为空"


@pytest.mark.asyncio
async def test_ac5_exception_error_message_pii_masked() -> None:
    content, sub = _make_content_and_sub()
    channel = AsyncMock()
    channel.distribute = AsyncMock(
        side_effect=AttributeError("failed sending to carol@corp.com via SMTP")
    )
    facade = _build_facade(channel, content, sub)

    with patch.object(facade, "_record_push", new=AsyncMock()) as mock_record:
        await facade.distribute(content_id=str(content.id), subscription_id=str(sub.id))

    kwargs = mock_record.call_args.kwargs
    error_msg = kwargs.get("error_message", "")
    assert "carol@corp.com" not in error_msg, (
        "异常路径 error_message 不得裸露原始 email PII"
    )


# ---------------------------------------------------------------------------
# AC6: 失败时结果字段正确：sent==0、skipped 累加、errors 有 reason、指标记 failed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ac6_failure_result_fields_correct_channel_response() -> None:
    content, sub = _make_content_and_sub()
    channel = AsyncMock()
    channel.distribute = AsyncMock(
        return_value={"status": "failed", "error": "smtp down"}
    )
    facade = _build_facade(channel, content, sub)

    with patch("intellisource.distributor.facade._record_push_outcome") as mock_outcome:
        result = await facade.distribute(
            content_id=str(content.id), subscription_id=str(sub.id)
        )

    assert result["sent"] == 0
    assert result["skipped"] == 1
    assert result["errors"], "errors 列表不得为空"
    assert result["errors"][0]["reason"] == "smtp down"

    outcomes = [c.args[0] for c in mock_outcome.call_args_list]
    assert "failed" in outcomes, "指标 pushes_total{status='failed'} 必须记录"
    assert "sent" not in outcomes


@pytest.mark.asyncio
async def test_ac6_failure_result_fields_correct_exception() -> None:
    content, sub = _make_content_and_sub()
    channel = AsyncMock()
    channel.distribute = AsyncMock(side_effect=AttributeError("no attribute 'body'"))
    facade = _build_facade(channel, content, sub)

    with patch("intellisource.distributor.facade._record_push_outcome") as mock_outcome:
        result = await facade.distribute(
            content_id=str(content.id), subscription_id=str(sub.id)
        )

    assert result["sent"] == 0
    assert result["skipped"] == 1
    assert result["errors"]
    assert "body" in result["errors"][0]["reason"]

    outcomes = [c.args[0] for c in mock_outcome.call_args_list]
    assert "failed" in outcomes
    assert "sent" not in outcomes
