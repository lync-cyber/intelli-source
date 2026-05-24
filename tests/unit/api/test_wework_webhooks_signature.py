"""Unit tests for WeWork webhook HTTP router under EncodingAESKey crypto (F-11).

Covers the WeWork GET handshake + POST message router contract via real HTTP
calls, using encrypted payloads produced by `build_encrypted_payload`. The
upstream contract was upgraded from plain SHA1 + clear-text echostr/XML to
EncodingAESKey AES-CBC; the unit-level crypto tests live in
`test_wecom_webhook_crypto.py` — this file pins the router-layer behaviour
(status codes, dispatch wiring, missing-crypto handling).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from intellisource.api.webhook_crypto import WeComCrypto, build_encrypted_payload

_TOKEN = "test_wework_token"
_ENCODING_AES_KEY = "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG"
_CORP_ID = "wx_corp_test_001"
_TIMESTAMP = "1700000000"
_NONCE = "ww_nonce_001"
_ECHO_PLAIN = "wework_verify_payload"

_TEXT_XML_PLAIN = (
    "<xml>"
    "<ToUserName><![CDATA[ww_account]]></ToUserName>"
    "<FromUserName><![CDATA[ww_user_001]]></FromUserName>"
    "<CreateTime>1700000000</CreateTime>"
    "<MsgType><![CDATA[text]]></MsgType>"
    "<Content><![CDATA[查最新的检索综述]]></Content>"
    "<MsgId>22345678901234</MsgId>"
    "</xml>"
)


def _make_webhooks_app(*, with_crypto: bool = True) -> FastAPI:
    """Create minimal FastAPI app with the webhooks router and WeWork wiring."""
    from intellisource.api.routers.webhooks import router as webhooks_router

    app = FastAPI()
    app.include_router(webhooks_router, prefix="/api/v1")

    if with_crypto:
        app.state.wecom_crypto = WeComCrypto(
            token=_TOKEN, encoding_aes_key=_ENCODING_AES_KEY, corp_id=_CORP_ID
        )

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


def _make_encrypted_post_body(plain_xml: str) -> tuple[str, str]:
    """Return (xml_envelope, msg_signature) for a POST message."""
    encrypt_b64, sig = build_encrypted_payload(
        _TOKEN, _ENCODING_AES_KEY, _CORP_ID, plain_xml, _TIMESTAMP, _NONCE
    )
    envelope = (
        "<xml>"
        f"<Encrypt><![CDATA[{encrypt_b64}]]></Encrypt>"
        f"<ToUserName><![CDATA[{_CORP_ID}]]></ToUserName>"
        "</xml>"
    )
    return envelope, sig


class TestGetWeworkWebhookCrypto:
    """F-11: GET /wework — EncodingAESKey URL verification."""

    @pytest.mark.asyncio
    async def test_get_correct_signature_decrypts_echostr(self) -> None:
        app = _make_webhooks_app()
        encrypt_b64, sig = build_encrypted_payload(
            _TOKEN, _ENCODING_AES_KEY, _CORP_ID, _ECHO_PLAIN, _TIMESTAMP, _NONCE
        )

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/api/v1/webhooks/wework",
                params={
                    "msg_signature": sig,
                    "timestamp": _TIMESTAMP,
                    "nonce": _NONCE,
                    "echostr": encrypt_b64,
                },
            )

        assert resp.status_code == 200, resp.text
        assert resp.text == _ECHO_PLAIN

    @pytest.mark.asyncio
    async def test_get_wrong_signature_returns_401(self) -> None:
        app = _make_webhooks_app()
        encrypt_b64, _correct_sig = build_encrypted_payload(
            _TOKEN, _ENCODING_AES_KEY, _CORP_ID, _ECHO_PLAIN, _TIMESTAMP, _NONCE
        )

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/api/v1/webhooks/wework",
                params={
                    "msg_signature": "invalid_signature_xyz",
                    "timestamp": _TIMESTAMP,
                    "nonce": _NONCE,
                    "echostr": encrypt_b64,
                },
            )

        assert resp.status_code == 401, resp.text

    @pytest.mark.asyncio
    async def test_get_missing_crypto_returns_503(self) -> None:
        app = _make_webhooks_app(with_crypto=False)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/api/v1/webhooks/wework",
                params={
                    "msg_signature": "anything",
                    "timestamp": _TIMESTAMP,
                    "nonce": _NONCE,
                    "echostr": "garbage",
                },
            )

        assert resp.status_code == 503, resp.text


class TestPostWeworkWebhookCrypto:
    """F-11: POST /wework — encrypted body decryption + dispatch."""

    @pytest.mark.asyncio
    async def test_post_wrong_signature_returns_401(self) -> None:
        app = _make_webhooks_app()
        envelope, _correct_sig = _make_encrypted_post_body(_TEXT_XML_PLAIN)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/webhooks/wework",
                content=envelope,
                params={
                    "msg_signature": "bad_signature",
                    "timestamp": _TIMESTAMP,
                    "nonce": _NONCE,
                },
                headers={"Content-Type": "application/xml"},
            )

        assert resp.status_code == 401, resp.text

    @pytest.mark.asyncio
    async def test_post_correct_signature_returns_xml_ack(self) -> None:
        app = _make_webhooks_app()
        envelope, sig = _make_encrypted_post_body(_TEXT_XML_PLAIN)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/webhooks/wework",
                content=envelope,
                params={
                    "msg_signature": sig,
                    "timestamp": _TIMESTAMP,
                    "nonce": _NONCE,
                },
                headers={"Content-Type": "application/xml"},
            )

        assert resp.status_code == 200, resp.text
        assert "<xml>" in resp.text and "success" in resp.text.lower()

    @pytest.mark.asyncio
    async def test_post_correct_signature_dispatches_chat_reply(self) -> None:
        app = _make_webhooks_app()
        envelope, sig = _make_encrypted_post_body(_TEXT_XML_PLAIN)

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
                    content=envelope,
                    params={
                        "msg_signature": sig,
                        "timestamp": _TIMESTAMP,
                        "nonce": _NONCE,
                    },
                    headers={"Content-Type": "application/xml"},
                )

        assert resp.status_code == 200
        import asyncio

        await asyncio.sleep(0)
        assert dispatch_calls, "expected _dispatch_chat_reply to be invoked"
        invocation = dispatch_calls[0]["kwargs"]
        assert invocation.get("openid") == "ww_user_001"
        assert "检索综述" in invocation.get("user_text", "")

    @pytest.mark.asyncio
    async def test_post_missing_crypto_returns_503(self) -> None:
        app = _make_webhooks_app(with_crypto=False)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/webhooks/wework",
                content="<xml></xml>",
                params={
                    "msg_signature": "any",
                    "timestamp": _TIMESTAMP,
                    "nonce": _NONCE,
                },
                headers={"Content-Type": "application/xml"},
            )

        assert resp.status_code == 503, resp.text
