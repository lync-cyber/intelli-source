"""Integration tests: POST /wechat webhook triggers CS callback (AC-12/5/9).

AC-12: POST correct signature + text message → cs_messenger.send_text(openid, content)
       called exactly once with the openid extracted from the XML body.
AC-5: _dispatch_chat_reply raises internally → endpoint logs error + falls back to
      fixed text (does not crash or surface 500 to caller).
AC-9: _dispatch_chat_reply calls run_flexible → extracts final answer → send_text.
"""

from __future__ import annotations

import hashlib
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sha1_sig(token: str, timestamp: str, nonce: str) -> str:
    raw = "".join(sorted([token, timestamp, nonce]))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


_TOKEN = "integration_test_token"
_TIMESTAMP = "1700001234"
_NONCE = "integration_nonce"
_OPENID = "o_openid_abc123"

_TEXT_XML = (
    "<xml>"
    f"<ToUserName><![CDATA[gh_test_account]]></ToUserName>"
    f"<FromUserName><![CDATA[{_OPENID}]]></FromUserName>"
    "<CreateTime>1700001234</CreateTime>"
    "<MsgType><![CDATA[text]]></MsgType>"
    "<Content><![CDATA[帮我查一下最新的 RAG 论文]]></Content>"
    "<MsgId>99887766554433</MsgId>"
    "</xml>"
)


def _make_app_with_spies() -> tuple[FastAPI, MagicMock]:
    """Build minimal app with spy cs_messenger and mock agent_runner."""
    from intellisource.api.routers.webhooks import (
        router as webhooks_router,
    )

    app = FastAPI()
    app.include_router(webhooks_router, prefix="/api/v1")

    app.state.wechat_webhook_token = _TOKEN

    mock_runner = MagicMock()
    mock_runner.run_flexible = AsyncMock(
        return_value={
            "status": "success",
            "steps_executed": 2,
            "results": [
                {"tool": "search", "output": {"items": []}},
                {
                    "tool": "summarize_for_user",
                    "output": {"text": "RAG 检索增强生成综述"},
                },
            ],
            "pipeline_name": "instant-search",
            "task_chain_id": "tc-integration-001",
        }
    )
    app.state.agent_runner = mock_runner

    mock_cs = MagicMock()
    mock_cs.send_text = AsyncMock(return_value=None)
    app.state.wechat_cs_messenger = mock_cs

    return app, mock_cs


# ---------------------------------------------------------------------------
# AC-12: spy cs_messenger.send_text called once with correct openid
# ---------------------------------------------------------------------------


class TestWebhookTriggersCsCallback:
    """AC-12: Correct POST triggers cs_messenger.send_text exactly once."""

    async def test_send_text_called_once_after_valid_post(self) -> None:
        """cs_messenger.send_text called once after valid POST with text message."""
        import asyncio

        app, mock_cs = _make_app_with_spies()
        sig = _sha1_sig(_TOKEN, _TIMESTAMP, _NONCE)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/webhooks/wechat",
                content=_TEXT_XML,
                params={
                    "signature": sig,
                    "timestamp": _TIMESTAMP,
                    "nonce": _NONCE,
                },
                headers={"Content-Type": "application/xml"},
            )

        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}: {resp.text}"
        )

        # Allow background task to complete
        await asyncio.sleep(0.1)

        (
            mock_cs.send_text.assert_called_once(),
            (
                f"cs_messenger.send_text must be called once, "
                f"got {mock_cs.send_text.call_count} call(s)"
            ),
        )

    async def test_send_text_called_with_correct_openid(self) -> None:
        """cs_messenger.send_text is called with the openid from the XML body."""
        import asyncio

        app, mock_cs = _make_app_with_spies()
        sig = _sha1_sig(_TOKEN, _TIMESTAMP, _NONCE)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            await client.post(
                "/api/v1/webhooks/wechat",
                content=_TEXT_XML,
                params={
                    "signature": sig,
                    "timestamp": _TIMESTAMP,
                    "nonce": _NONCE,
                },
                headers={"Content-Type": "application/xml"},
            )

        await asyncio.sleep(0.1)

        mock_cs.send_text.assert_called_once()
        call_args = mock_cs.send_text.call_args
        # openid must appear in positional or keyword args
        all_args_str = str(call_args)
        assert _OPENID in all_args_str, (
            f"Expected openid '{_OPENID}' in send_text call args: {all_args_str}"
        )


# ---------------------------------------------------------------------------
# AC-9: _dispatch_chat_reply internal flow
# ---------------------------------------------------------------------------


class TestDispatchChatReply:
    """AC-9: _dispatch_chat_reply runs run_flexible, extracts answer, send_text."""

    async def test_dispatch_chat_reply_calls_run_flexible(self) -> None:
        """_dispatch_chat_reply invokes runner.run_flexible with user text."""
        from intellisource.api.routers.webhooks import (
            _dispatch_chat_reply,
        )

        mock_runner = MagicMock()
        mock_runner.run_flexible = AsyncMock(
            return_value={
                "status": "success",
                "steps_executed": 2,
                "results": [
                    {"tool": "summarize_for_user", "output": {"text": "答案文本"}}
                ],
                "pipeline_name": "instant-search",
                "task_chain_id": "tc-unit-test",
            }
        )
        mock_cs = MagicMock()
        mock_cs.send_text = AsyncMock(return_value=None)

        await _dispatch_chat_reply(
            runner=mock_runner,
            cs_messenger=mock_cs,
            openid=_OPENID,
            user_text="查询最新 RAG 论文",
        )

        mock_runner.run_flexible.assert_awaited_once()
        call_kwargs = mock_runner.run_flexible.call_args
        assert "查询最新 RAG 论文" in str(call_kwargs), (
            f"user_text not forwarded to run_flexible: {call_kwargs}"
        )

    async def test_dispatch_chat_reply_calls_send_text_with_answer(self) -> None:
        """_dispatch_chat_reply passes extracted answer text to send_text."""
        from intellisource.api.routers.webhooks import (
            _dispatch_chat_reply,
        )

        expected_answer = "RAG（检索增强生成）综述：..."
        mock_runner = MagicMock()
        mock_runner.run_flexible = AsyncMock(
            return_value={
                "status": "success",
                "steps_executed": 2,
                "results": [
                    {"tool": "summarize_for_user", "output": {"text": expected_answer}}
                ],
                "pipeline_name": "instant-search",
                "task_chain_id": "tc-unit-test-2",
            }
        )
        mock_cs = MagicMock()
        mock_cs.send_text = AsyncMock(return_value=None)

        await _dispatch_chat_reply(
            runner=mock_runner,
            cs_messenger=mock_cs,
            openid=_OPENID,
            user_text="query",
        )

        mock_cs.send_text.assert_awaited_once()
        call_str = str(mock_cs.send_text.call_args)
        assert _OPENID in call_str, f"openid missing from send_text call: {call_str}"
        assert expected_answer in call_str, (
            f"Expected answer '{expected_answer}' in send_text call: {call_str}"
        )

    async def test_dispatch_chat_reply_falls_back_on_exception(self) -> None:
        """_dispatch_chat_reply sends fallback text when run_flexible raises."""
        from intellisource.api.routers.webhooks import (
            _dispatch_chat_reply,
        )

        mock_runner = MagicMock()
        mock_runner.run_flexible = AsyncMock(
            side_effect=RuntimeError("LLM unavailable")
        )
        mock_cs = MagicMock()
        mock_cs.send_text = AsyncMock(return_value=None)

        # Must not raise — fallback text should be sent
        await _dispatch_chat_reply(
            runner=mock_runner,
            cs_messenger=mock_cs,
            openid=_OPENID,
            user_text="任何查询",
        )

        (
            mock_cs.send_text.assert_awaited_once(),
            ("send_text must still be called with fallback text on run_flexible fail"),
        )
        call_str = str(mock_cs.send_text.call_args)
        assert _OPENID in call_str, (
            f"openid missing from fallback send_text: {call_str}"
        )
