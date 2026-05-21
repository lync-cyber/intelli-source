"""Tests for Webhook callback handling (T-039).

Covers:
- AC-T039-1: WeChat signature verification (sha1(sort(token, timestamp, nonce)))
- AC-T039-2: WeWork (Enterprise WeChat) signature verification
- AC-T039-3: XML message body parsing
- AC-T039-4: Text message routing to search module
- AC-T039-5: Signature failure returns 403
- AC-T039-6: Async processing with 5-second response deadline
"""

from __future__ import annotations

import hashlib
import time
from unittest.mock import AsyncMock

import pytest

# ---------------------------------------------------------------------------
# Import guard — module does not exist yet (RED phase)
# ---------------------------------------------------------------------------

try:
    from intellisource.distributor.webhooks import (
        WeChatWebhookHandler,
        WeWorkWebhookHandler,
    )
except ImportError:
    WeChatWebhookHandler = None  # type: ignore[assignment,misc]
    WeWorkWebhookHandler = None  # type: ignore[assignment,misc]

_MODULE_MISSING = WeChatWebhookHandler is None

# ---------------------------------------------------------------------------
# Test data helpers
# ---------------------------------------------------------------------------

_WECHAT_TOKEN = "test_wechat_token"
_WEWORK_TOKEN = "test_wework_token"
_WEWORK_ENCODING_AES_KEY = "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG"
_WEWORK_CORP_ID = "ww_test_corp_id"


def _make_wechat_signature(token: str, timestamp: str, nonce: str) -> str:
    """Compute a valid WeChat signature for testing."""
    parts = sorted([token, timestamp, nonce])
    raw = "".join(parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


_SAMPLE_TEXT_XML = (
    "<xml>"
    "<ToUserName><![CDATA[gh_test]]></ToUserName>"
    "<FromUserName><![CDATA[o_user_openid]]></FromUserName>"
    "<CreateTime>1348831860</CreateTime>"
    "<MsgType><![CDATA[text]]></MsgType>"
    "<Content><![CDATA[hello world]]></Content>"
    "<MsgId>1234567890123456</MsgId>"
    "</xml>"
)

_SAMPLE_IMAGE_XML = (
    "<xml>"
    "<ToUserName><![CDATA[gh_test]]></ToUserName>"
    "<FromUserName><![CDATA[o_user_openid]]></FromUserName>"
    "<CreateTime>1348831860</CreateTime>"
    "<MsgType><![CDATA[image]]></MsgType>"
    "<PicUrl><![CDATA[http://example.com/pic.jpg]]></PicUrl>"
    "<MediaId><![CDATA[media_id_001]]></MediaId>"
    "<MsgId>1234567890123457</MsgId>"
    "</xml>"
)

_MALFORMED_XML = "<xml><ToUserName>unclosed"


# ===================================================================
# AC-T039-1: WeChat signature verification
# ===================================================================


class TestWeChatSignatureVerification:
    """AC-T039-1: WeChat signature = sha1(sort([token, timestamp, nonce]))."""

    def test_valid_signature_passes(self) -> None:
        """Valid signature should be accepted by verify_signature."""
        if _MODULE_MISSING:
            pytest.fail("intellisource.distributor.webhooks not implemented")

        handler = WeChatWebhookHandler(token=_WECHAT_TOKEN)
        timestamp = str(int(time.time()))
        nonce = "random_nonce_123"
        signature = _make_wechat_signature(_WECHAT_TOKEN, timestamp, nonce)

        result = handler.verify_signature(
            signature=signature, timestamp=timestamp, nonce=nonce
        )
        assert result is True

    def test_invalid_signature_rejected(self) -> None:
        """Tampered signature should be rejected."""
        if _MODULE_MISSING:
            pytest.fail("intellisource.distributor.webhooks not implemented")

        handler = WeChatWebhookHandler(token=_WECHAT_TOKEN)
        timestamp = str(int(time.time()))
        nonce = "random_nonce_456"

        result = handler.verify_signature(
            signature="invalid_signature_value", timestamp=timestamp, nonce=nonce
        )
        assert result is False

    def test_empty_signature_rejected(self) -> None:
        """Empty signature string should be rejected."""
        if _MODULE_MISSING:
            pytest.fail("intellisource.distributor.webhooks not implemented")

        handler = WeChatWebhookHandler(token=_WECHAT_TOKEN)
        result = handler.verify_signature(
            signature="", timestamp="12345", nonce="nonce"
        )
        assert result is False


# ===================================================================
# AC-T039-2: WeWork (Enterprise WeChat) signature verification
# ===================================================================


class TestWeWorkSignatureVerification:
    """AC-T039-2: Enterprise WeChat signature verification."""

    def test_valid_wework_signature_passes(self) -> None:
        """Valid WeWork signature should be accepted."""
        if _MODULE_MISSING:
            pytest.fail("intellisource.distributor.webhooks not implemented")

        handler = WeWorkWebhookHandler(
            token=_WEWORK_TOKEN,
            encoding_aes_key=_WEWORK_ENCODING_AES_KEY,
            corp_id=_WEWORK_CORP_ID,
        )
        timestamp = str(int(time.time()))
        nonce = "wework_nonce_789"
        # WeWork uses the same sha1(sort) algorithm for signature
        signature = _make_wechat_signature(_WEWORK_TOKEN, timestamp, nonce)

        result = handler.verify_signature(
            signature=signature, timestamp=timestamp, nonce=nonce
        )
        assert result is True

    def test_invalid_wework_signature_rejected(self) -> None:
        """Invalid WeWork signature should be rejected."""
        if _MODULE_MISSING:
            pytest.fail("intellisource.distributor.webhooks not implemented")

        handler = WeWorkWebhookHandler(
            token=_WEWORK_TOKEN,
            encoding_aes_key=_WEWORK_ENCODING_AES_KEY,
            corp_id=_WEWORK_CORP_ID,
        )
        result = handler.verify_signature(
            signature="bad_sig", timestamp="12345", nonce="nonce"
        )
        assert result is False

    def test_wework_handler_stores_corp_id(self) -> None:
        """WeWorkWebhookHandler should store corp_id for decryption context."""
        if _MODULE_MISSING:
            pytest.fail("intellisource.distributor.webhooks not implemented")

        handler = WeWorkWebhookHandler(
            token=_WEWORK_TOKEN,
            encoding_aes_key=_WEWORK_ENCODING_AES_KEY,
            corp_id=_WEWORK_CORP_ID,
        )
        assert handler.corp_id == _WEWORK_CORP_ID


# ===================================================================
# AC-T039-3: XML message body parsing
# ===================================================================


class TestXMLMessageParsing:
    """AC-T039-3: Parse incoming XML message bodies."""

    def test_parse_text_message(self) -> None:
        """parse_message should extract fields from a text XML message."""
        if _MODULE_MISSING:
            pytest.fail("intellisource.distributor.webhooks not implemented")

        handler = WeChatWebhookHandler(token=_WECHAT_TOKEN)
        msg = handler.parse_message(_SAMPLE_TEXT_XML)

        assert msg is not None
        assert msg["MsgType"] == "text"
        assert msg["Content"] == "hello world"
        assert msg["FromUserName"] == "o_user_openid"

    def test_parse_image_message(self) -> None:
        """parse_message should handle image-type XML messages."""
        if _MODULE_MISSING:
            pytest.fail("intellisource.distributor.webhooks not implemented")

        handler = WeChatWebhookHandler(token=_WECHAT_TOKEN)
        msg = handler.parse_message(_SAMPLE_IMAGE_XML)

        assert msg is not None
        assert msg["MsgType"] == "image"
        assert "PicUrl" in msg

    def test_parse_malformed_xml_returns_none_or_raises(self) -> None:
        """parse_message should handle malformed XML gracefully."""
        if _MODULE_MISSING:
            pytest.fail("intellisource.distributor.webhooks not implemented")

        handler = WeChatWebhookHandler(token=_WECHAT_TOKEN)
        # Should either return None or raise ValueError for malformed XML
        try:
            result = handler.parse_message(_MALFORMED_XML)
            assert result is None
        except ValueError:
            pass  # Also acceptable


# ===================================================================
# AC-T039-4: Text message routing to search module
# ===================================================================


class TestTextMessageRouting:
    """AC-T039-4: Text messages are routed to the search module."""

    @pytest.mark.asyncio
    async def test_handle_text_routes_to_search(self) -> None:
        """handle_message should route text content to search module."""
        if _MODULE_MISSING:
            pytest.fail("intellisource.distributor.webhooks not implemented")

        mock_search = AsyncMock()
        mock_search.search = AsyncMock(return_value=[{"title": "result1"}])

        handler = WeChatWebhookHandler(token=_WECHAT_TOKEN)
        await handler.handle_message(_SAMPLE_TEXT_XML, search_service=mock_search)

        # Search should have been called with the message content
        mock_search.search.assert_called_once()
        call_args = mock_search.search.call_args
        # The query should contain the text content "hello world"
        assert "hello world" in str(call_args)

    @pytest.mark.asyncio
    async def test_handle_text_returns_xml_response(self) -> None:
        """handle_message should return a valid XML response string."""
        if _MODULE_MISSING:
            pytest.fail("intellisource.distributor.webhooks not implemented")

        mock_search = AsyncMock()
        mock_search.search = AsyncMock(return_value=[{"title": "result1"}])

        handler = WeChatWebhookHandler(token=_WECHAT_TOKEN)
        response = await handler.handle_message(
            _SAMPLE_TEXT_XML, search_service=mock_search
        )

        assert isinstance(response, str)
        assert "<xml>" in response
        assert "</xml>" in response

    @pytest.mark.asyncio
    async def test_non_text_message_not_routed_to_search(self) -> None:
        """Non-text messages (e.g., image) should not trigger search."""
        if _MODULE_MISSING:
            pytest.fail("intellisource.distributor.webhooks not implemented")

        mock_search = AsyncMock()
        mock_search.search = AsyncMock(return_value=[])

        handler = WeChatWebhookHandler(token=_WECHAT_TOKEN)
        await handler.handle_message(_SAMPLE_IMAGE_XML, search_service=mock_search)

        mock_search.search.assert_not_called()


# ===================================================================
# AC-T039-5: Signature failure returns 403
# ===================================================================


class TestSignatureFailure403:
    """AC-T039-5: Failed signature verification results in 403."""

    @pytest.mark.asyncio
    async def test_handle_request_returns_403_on_bad_signature(self) -> None:
        """handle_request should return 403 status when signature is invalid."""
        if _MODULE_MISSING:
            pytest.fail("intellisource.distributor.webhooks not implemented")

        handler = WeChatWebhookHandler(token=_WECHAT_TOKEN)
        result = await handler.handle_request(
            signature="wrong_sig",
            timestamp="12345",
            nonce="nonce",
            body=_SAMPLE_TEXT_XML,
        )
        assert result["status_code"] == 403

    @pytest.mark.asyncio
    async def test_handle_request_returns_403_on_missing_signature(self) -> None:
        """handle_request should return 403 when signature is missing/empty."""
        if _MODULE_MISSING:
            pytest.fail("intellisource.distributor.webhooks not implemented")

        handler = WeChatWebhookHandler(token=_WECHAT_TOKEN)
        result = await handler.handle_request(
            signature="",
            timestamp="12345",
            nonce="nonce",
            body=_SAMPLE_TEXT_XML,
        )
        assert result["status_code"] == 403

    @pytest.mark.asyncio
    async def test_handle_request_succeeds_with_valid_signature(self) -> None:
        """handle_request should process message when signature is valid."""
        if _MODULE_MISSING:
            pytest.fail("intellisource.distributor.webhooks not implemented")

        handler = WeChatWebhookHandler(token=_WECHAT_TOKEN)
        timestamp = str(int(time.time()))
        nonce = "valid_nonce"
        signature = _make_wechat_signature(_WECHAT_TOKEN, timestamp, nonce)

        mock_search = AsyncMock()
        mock_search.search = AsyncMock(return_value=[])

        result = await handler.handle_request(
            signature=signature,
            timestamp=timestamp,
            nonce=nonce,
            body=_SAMPLE_TEXT_XML,
            search_service=mock_search,
        )
        assert result["status_code"] == 200


# ===================================================================
# AC-T039-6: Async processing with 5-second response deadline
# ===================================================================


class TestAsyncProcessingDeadline:
    """AC-T039-6: Async processing ensures response within 5 seconds."""

    @pytest.mark.asyncio
    async def test_response_deadline_constant_defined(self) -> None:
        """Module should define RESPONSE_DEADLINE_SECONDS = 5."""
        if _MODULE_MISSING:
            pytest.fail("intellisource.distributor.webhooks not implemented")

        from intellisource.distributor.webhooks import RESPONSE_DEADLINE_SECONDS

        assert RESPONSE_DEADLINE_SECONDS == 5

    @pytest.mark.asyncio
    async def test_slow_search_returns_ack_within_deadline(self) -> None:
        """If search takes too long, handler returns acknowledgement quickly
        and defers processing to background."""
        if _MODULE_MISSING:
            pytest.fail("intellisource.distributor.webhooks not implemented")

        import asyncio

        async def slow_search(*args, **kwargs):
            await asyncio.sleep(10)  # Simulate slow search
            return [{"title": "late result"}]

        mock_search = AsyncMock()
        mock_search.search = slow_search

        handler = WeChatWebhookHandler(token=_WECHAT_TOKEN)
        timestamp = str(int(time.time()))
        nonce = "deadline_nonce"
        signature = _make_wechat_signature(_WECHAT_TOKEN, timestamp, nonce)

        result = await handler.handle_request(
            signature=signature,
            timestamp=timestamp,
            nonce=nonce,
            body=_SAMPLE_TEXT_XML,
            search_service=mock_search,
        )
        # Should return 200 (ack) even though search is slow
        assert result["status_code"] == 200

    @pytest.mark.asyncio
    async def test_handle_message_is_async(self) -> None:
        """handle_message should be an async method (coroutine function)."""
        if _MODULE_MISSING:
            pytest.fail("intellisource.distributor.webhooks not implemented")

        import inspect

        assert inspect.iscoroutinefunction(WeChatWebhookHandler.handle_message)
