"""Unit tests for WeChat webhook signature verification via HTTP router (AC-5/11).

AC-5: GET /wechat validates URL signature and returns echostr; POST validates
      signature then dispatches async _dispatch_chat_reply and returns XML ack.
AC-11: Wrong signature returns 403; correct signature passes.
"""

from __future__ import annotations

import hashlib
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _sha1_sig(token: str, timestamp: str, nonce: str) -> str:
    raw = "".join(sorted([token, timestamp, nonce]))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


_TOKEN = "test_wechat_token"
_TIMESTAMP = "1700000000"
_NONCE = "abc123"
_ECHOSTR = "verify_me_now"

_TEXT_XML = (
    "<xml>"
    "<ToUserName><![CDATA[gh_test]]></ToUserName>"
    "<FromUserName><![CDATA[openid_user_001]]></FromUserName>"
    "<CreateTime>1700000000</CreateTime>"
    "<MsgType><![CDATA[text]]></MsgType>"
    "<Content><![CDATA[帮我查一下最新的 RAG 论文]]></Content>"
    "<MsgId>12345678901234</MsgId>"
    "</xml>"
)


def _make_webhooks_app() -> FastAPI:
    """Create minimal FastAPI app with the webhooks router mounted."""
    from intellisource.api.routers.webhooks import (
        router as webhooks_router,
    )

    app = FastAPI()
    app.include_router(webhooks_router, prefix="/api/v1")
    # Inject minimal state so handler can access token + cs_messenger
    app.state.wechat_webhook_token = _TOKEN
    mock_runner = MagicMock()
    mock_runner.run_flexible = AsyncMock(
        return_value={
            "status": "success",
            "steps_executed": 2,
            "results": [{"tool": "summarize_for_user", "output": {"text": "RAG 综述"}}],
            "pipeline_name": "instant-search",
            "task_chain_id": "tc-test",
        }
    )
    app.state.agent_runner = mock_runner
    mock_cs = MagicMock()
    mock_cs.send_text = AsyncMock(return_value=None)
    app.state.wechat_cs_messenger = mock_cs
    return app


# ---------------------------------------------------------------------------
# AC-5 + AC-11: GET /api/v1/webhooks/wechat — URL verify flow
# ---------------------------------------------------------------------------


class TestGetWechatWebhookSignature:
    """AC-5/AC-11: GET /wechat endpoint for WeChat server URL verification."""

    async def test_get_correct_signature_returns_echostr(self) -> None:
        """Correct signature on GET returns the echostr with 200."""
        app = _make_webhooks_app()
        sig = _sha1_sig(_TOKEN, _TIMESTAMP, _NONCE)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/api/v1/webhooks/wechat",
                params={
                    "signature": sig,
                    "timestamp": _TIMESTAMP,
                    "nonce": _NONCE,
                    "echostr": _ECHOSTR,
                },
            )

        assert resp.status_code == 200, (
            f"Expected 200 for valid signature, got {resp.status_code}: {resp.text}"
        )
        assert _ECHOSTR in resp.text, (
            f"Expected echostr '{_ECHOSTR}' in response, got: {resp.text}"
        )

    async def test_get_wrong_signature_returns_403(self) -> None:
        """Wrong signature on GET returns 403."""
        app = _make_webhooks_app()

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/api/v1/webhooks/wechat",
                params={
                    "signature": "invalid_signature_xyz",
                    "timestamp": _TIMESTAMP,
                    "nonce": _NONCE,
                    "echostr": _ECHOSTR,
                },
            )

        assert resp.status_code == 403, (
            f"Expected 403 for wrong signature, got {resp.status_code}: {resp.text}"
        )

    async def test_get_missing_signature_returns_403(self) -> None:
        """Empty/missing signature on GET returns 403."""
        app = _make_webhooks_app()

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/api/v1/webhooks/wechat",
                params={
                    "signature": "",
                    "timestamp": _TIMESTAMP,
                    "nonce": _NONCE,
                    "echostr": _ECHOSTR,
                },
            )

        assert resp.status_code == 403, (
            f"Expected 403 for empty signature, got {resp.status_code}"
        )


# ---------------------------------------------------------------------------
# AC-5 + AC-11: POST /api/v1/webhooks/wechat — message handling
# ---------------------------------------------------------------------------


class TestPostWechatWebhookSignature:
    """AC-5/AC-11: POST /wechat signature validation for incoming messages."""

    async def test_post_wrong_signature_returns_403(self) -> None:
        """POST with wrong signature must return 403 before processing."""
        app = _make_webhooks_app()

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/webhooks/wechat",
                content=_TEXT_XML,
                params={
                    "signature": "bad_signature_value",
                    "timestamp": _TIMESTAMP,
                    "nonce": _NONCE,
                },
                headers={"Content-Type": "application/xml"},
            )

        assert resp.status_code == 403, (
            f"Expected 403 for wrong POST sig, got {resp.status_code}: {resp.text}"
        )

    async def test_post_correct_signature_returns_xml_ack(self) -> None:
        """POST with correct signature + text body returns XML ack with 200."""
        app = _make_webhooks_app()
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
            f"Expected 200 for valid POST, got {resp.status_code}: {resp.text}"
        )
        # Response must be XML ack — sync return without waiting for background task
        assert "<xml>" in resp.text or "success" in resp.text.lower(), (
            f"Expected XML ack in response, got: {resp.text}"
        )

    async def test_post_correct_signature_returns_synchronously(self) -> None:
        """POST returns ack synchronously (does not wait for _dispatch_chat_reply)."""
        app = _make_webhooks_app()
        sig = _sha1_sig(_TOKEN, _TIMESTAMP, _NONCE)

        # _dispatch_chat_reply is a slow coroutine — POST must still return fast
        async def slow_dispatch(*args: Any, **kwargs: Any) -> None:
            import asyncio

            await asyncio.sleep(10)

        with patch(
            "intellisource.api.routers.webhooks._dispatch_chat_reply",
            new=AsyncMock(side_effect=slow_dispatch),
        ):
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

        # Should still return 200 quickly despite slow dispatch
        assert resp.status_code == 200, (
            f"Expected 200 for sync POST ack, got {resp.status_code}"
        )
