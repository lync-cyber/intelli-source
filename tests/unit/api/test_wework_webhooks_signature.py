"""Unit tests for WeWork webhook signature verification via HTTP router (R-005).

Mirror of test_webhooks_signature.py for the WeWork side. Required to close
the test-quality gap that previously let WeWork POST handler ship without any
signature verification (R-002).

AC-9/AC-11: WeWork GET handshake + POST message handling honour msg_signature.
"""

from __future__ import annotations

import hashlib
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


def _sha1_sig(token: str, timestamp: str, nonce: str) -> str:
    raw = "".join(sorted([token, timestamp, nonce]))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


_TOKEN = "test_wework_token"
_TIMESTAMP = "1700000000"
_NONCE = "ww_nonce_001"
_ECHOSTR = "wework_verify_payload"

_TEXT_XML = (
    "<xml>"
    "<ToUserName><![CDATA[ww_account]]></ToUserName>"
    "<FromUserName><![CDATA[ww_user_001]]></FromUserName>"
    "<CreateTime>1700000000</CreateTime>"
    "<MsgType><![CDATA[text]]></MsgType>"
    "<Content><![CDATA[查最新的检索综述]]></Content>"
    "<MsgId>22345678901234</MsgId>"
    "</xml>"
)


def _make_webhooks_app() -> FastAPI:
    """Create minimal FastAPI app with the webhooks router and WeWork state."""
    from intellisource.api.routers.webhooks import router as webhooks_router

    app = FastAPI()
    app.include_router(webhooks_router, prefix="/api/v1")
    app.state.wework_webhook_token = _TOKEN
    mock_runner = MagicMock()
    mock_runner.run_flexible = AsyncMock(
        return_value={
            "status": "success",
            "steps_executed": 2,
            "results": [{"tool": "summarize_for_user", "output": {"text": "综述回复"}}],
            "pipeline_name": "instant-search",
            "task_chain_id": "tc-ww",
        }
    )
    app.state.agent_runner = mock_runner
    mock_cs = MagicMock()
    mock_cs.send_text = AsyncMock(return_value=None)
    app.state.wework_cs_messenger = mock_cs
    app.state.background_tasks = set()
    return app


class TestGetWeworkWebhookSignature:
    """R-005/AC-11: GET /wework — verification handshake."""

    async def test_get_correct_signature_returns_echostr(self) -> None:
        """Correct signature on GET returns the echostr with 200."""
        app = _make_webhooks_app()
        sig = _sha1_sig(_TOKEN, _TIMESTAMP, _NONCE)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/api/v1/webhooks/wework",
                params={
                    "msg_signature": sig,
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
                "/api/v1/webhooks/wework",
                params={
                    "msg_signature": "invalid_signature_xyz",
                    "timestamp": _TIMESTAMP,
                    "nonce": _NONCE,
                    "echostr": _ECHOSTR,
                },
            )

        assert resp.status_code == 403, (
            f"Expected 403 for wrong signature, got {resp.status_code}: {resp.text}"
        )

    async def test_get_empty_signature_returns_403(self) -> None:
        """Empty signature on GET returns 403."""
        app = _make_webhooks_app()

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/api/v1/webhooks/wework",
                params={
                    "msg_signature": "",
                    "timestamp": _TIMESTAMP,
                    "nonce": _NONCE,
                    "echostr": _ECHOSTR,
                },
            )

        assert resp.status_code == 403


class TestPostWeworkWebhookSignature:
    """R-005/AC-11: POST /wework signature validation for inbound messages."""

    async def test_post_wrong_signature_returns_403(self) -> None:
        """POST with wrong msg_signature must return 403 before processing."""
        app = _make_webhooks_app()

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/webhooks/wework",
                content=_TEXT_XML,
                params={
                    "msg_signature": "bad_signature",
                    "timestamp": _TIMESTAMP,
                    "nonce": _NONCE,
                },
                headers={"Content-Type": "application/xml"},
            )

        assert resp.status_code == 403, (
            f"Expected 403 for wrong POST sig, got {resp.status_code}: {resp.text}"
        )

    async def test_post_empty_signature_returns_403(self) -> None:
        """POST with empty msg_signature must return 403."""
        app = _make_webhooks_app()

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/webhooks/wework",
                content=_TEXT_XML,
                params={
                    "msg_signature": "",
                    "timestamp": _TIMESTAMP,
                    "nonce": _NONCE,
                },
                headers={"Content-Type": "application/xml"},
            )

        assert resp.status_code == 403

    async def test_post_correct_signature_returns_xml_ack(self) -> None:
        """POST with correct msg_signature + text body returns XML ack with 200."""
        app = _make_webhooks_app()
        sig = _sha1_sig(_TOKEN, _TIMESTAMP, _NONCE)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/webhooks/wework",
                content=_TEXT_XML,
                params={
                    "msg_signature": sig,
                    "timestamp": _TIMESTAMP,
                    "nonce": _NONCE,
                },
                headers={"Content-Type": "application/xml"},
            )

        assert resp.status_code == 200, (
            f"Expected 200 for valid POST, got {resp.status_code}: {resp.text}"
        )
        assert "<xml>" in resp.text or "success" in resp.text.lower(), (
            f"Expected XML ack in response, got: {resp.text}"
        )

    async def test_post_correct_signature_dispatches_chat_reply(self) -> None:
        """POST with valid signature spawns _dispatch_chat_reply on event loop."""
        app = _make_webhooks_app()
        sig = _sha1_sig(_TOKEN, _TIMESTAMP, _NONCE)

        dispatch_calls: list[dict[str, Any]] = []

        async def fake_dispatch(*args: Any, **kwargs: Any) -> None:
            dispatch_calls.append({"args": args, "kwargs": kwargs})

        with patch(
            "intellisource.api.routers.webhooks._dispatch_chat_reply",
            new=AsyncMock(side_effect=fake_dispatch),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/v1/webhooks/wework",
                    content=_TEXT_XML,
                    params={
                        "msg_signature": sig,
                        "timestamp": _TIMESTAMP,
                        "nonce": _NONCE,
                    },
                    headers={"Content-Type": "application/xml"},
                )

        assert resp.status_code == 200
        # Background task should have been scheduled — give the loop a tick.
        # Use a small sleep to let the event loop drain the dispatched task.
        import asyncio

        await asyncio.sleep(0)
        assert dispatch_calls, (
            "_dispatch_chat_reply was not invoked after a valid signed POST"
        )
        invocation = dispatch_calls[0]["kwargs"]
        assert invocation.get("openid") == "ww_user_001"
        assert "检索综述" in invocation.get("user_text", "")
