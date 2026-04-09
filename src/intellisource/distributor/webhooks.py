"""Webhook callback handling for WeChat and WeWork (Enterprise WeChat)."""

from __future__ import annotations

import asyncio
import hashlib
import xml.etree.ElementTree as ET
from typing import Any

RESPONSE_DEADLINE_SECONDS: int = 5


def _verify_sha1_signature(
    token: str, *, signature: str, timestamp: str, nonce: str
) -> bool:
    """Verify a SHA-1 signature: sha1(sort([token, timestamp, nonce]))."""
    if not signature:
        return False
    raw = "".join(sorted([token, timestamp, nonce]))
    expected = hashlib.sha1(raw.encode("utf-8")).hexdigest()
    return signature == expected


class WeChatWebhookHandler:
    """Handler for WeChat Official Account webhook callbacks."""

    def __init__(self, token: str) -> None:
        self._token = token

    def verify_signature(self, *, signature: str, timestamp: str, nonce: str) -> bool:
        """Verify WeChat signature using sha1(sort([token, timestamp, nonce]))."""
        return _verify_sha1_signature(
            self._token, signature=signature, timestamp=timestamp, nonce=nonce
        )

    def parse_message(self, xml_body: str) -> dict[str, str] | None:
        """Parse incoming XML message body into a dict of fields."""
        try:
            root = ET.fromstring(xml_body)  # noqa: S314
        except ET.ParseError:
            return None
        result: dict[str, str] = {}
        for child in root:
            if child.text is not None:
                result[child.tag] = child.text
        return result if result else None

    async def handle_message(self, xml_body: str, search_service: Any) -> str:
        """Handle a parsed message, routing text messages to search."""
        msg = self.parse_message(xml_body)

        if msg is not None and msg.get("MsgType") == "text":
            await search_service.search(query=msg.get("Content", ""))

        from_user = msg.get("FromUserName", "") if msg is not None else ""
        to_user = msg.get("ToUserName", "") if msg is not None else ""

        return (
            "<xml>"
            f"<ToUserName><![CDATA[{from_user}]]></ToUserName>"
            f"<FromUserName><![CDATA[{to_user}]]></FromUserName>"
            f"<CreateTime>{0}</CreateTime>"
            "<MsgType><![CDATA[text]]></MsgType>"
            "<Content><![CDATA[success]]></Content>"
            "</xml>"
        )

    async def handle_request(
        self,
        *,
        signature: str,
        timestamp: str,
        nonce: str,
        body: str,
        search_service: Any = None,
    ) -> dict[str, Any]:
        """Handle a full webhook request with signature verification and deadline."""
        if not self.verify_signature(
            signature=signature, timestamp=timestamp, nonce=nonce
        ):
            return {"status_code": 403}

        if search_service is not None:
            try:
                async with asyncio.timeout(RESPONSE_DEADLINE_SECONDS):
                    response_body = await self.handle_message(
                        body, search_service=search_service
                    )
            except TimeoutError:
                response_body = ""
        else:
            response_body = ""

        return {"status_code": 200, "body": response_body}


class WeWorkWebhookHandler:
    """Handler for WeWork (Enterprise WeChat) webhook callbacks."""

    def __init__(self, *, token: str, encoding_aes_key: str, corp_id: str) -> None:
        self._token = token
        self._encoding_aes_key = encoding_aes_key
        self.corp_id = corp_id

    def verify_signature(self, *, signature: str, timestamp: str, nonce: str) -> bool:
        """Verify WeWork signature using sha1(sort([token, timestamp, nonce]))."""
        return _verify_sha1_signature(
            self._token, signature=signature, timestamp=timestamp, nonce=nonce
        )
