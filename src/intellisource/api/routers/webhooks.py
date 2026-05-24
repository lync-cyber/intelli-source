"""Webhooks router for WeChat and WeWork inbound message callbacks (AC-5/6/9/11/12)."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import xml.etree.ElementTree as ET
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import PlainTextResponse

from intellisource.agent.tools import load_pipeline_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

_FALLBACK_TEXT = "抱歉，服务暂时不可用，请稍后再试。"
_MAX_USER_TEXT_CHARS: int = 1024


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _verify_sha1(token: str, *, signature: str, timestamp: str, nonce: str) -> bool:
    if not token or not signature:
        return False
    raw = "".join(sorted([token, timestamp, nonce]))
    expected = hashlib.sha1(raw.encode("utf-8")).hexdigest()
    return signature == expected


def _parse_xml_text_message(xml_body: str) -> dict[str, str] | None:
    try:
        root = ET.fromstring(xml_body)  # noqa: S314
    except ET.ParseError:
        return None
    result: dict[str, str] = {}
    for child in root:
        if child.text is not None:
            result[child.tag] = child.text
    return result if result else None


def _extract_answer(result: dict[str, Any]) -> str:
    final_answer = result.get("final_answer")
    if final_answer:
        return str(final_answer)
    for step in reversed(result.get("results", [])):
        output = step.get("output", {})
        text = output.get("text", "")
        if text:
            return str(text)
    return ""


async def _dispatch_chat_reply(
    runner: Any,
    cs_messenger: Any,
    openid: str,
    user_text: str,
) -> None:
    """Call run_flexible, extract answer, and send via cs_messenger.send_text."""
    try:
        config = load_pipeline_config("instant-search")
        flex_result = await runner.run_flexible(
            config,
            user_message=user_text,
            session={},
        )
        answer = _extract_answer(flex_result)
        if not answer:
            answer = _FALLBACK_TEXT
        await cs_messenger.send_text(openid=openid, content=answer)
    except Exception:
        logger.exception(
            "_dispatch_chat_reply failed for openid=%s", openid, extra={"alert": True}
        )
        try:
            await cs_messenger.send_text(openid=openid, content=_FALLBACK_TEXT)
        except Exception:
            logger.exception(
                "Fallback send_text also failed for openid=%s",
                openid,
                extra={"alert": True},
            )


def _spawn_background_dispatch(
    app: Any,
    runner: Any,
    cs_messenger: Any,
    openid: str,
    user_text: str,
) -> None:
    """Spawn `_dispatch_chat_reply` and retain a strong task reference.

    `asyncio.create_task` only holds a weak reference to the task; without
    retaining the result the task can be garbage-collected mid-flight,
    producing "Task was destroyed but it is pending" and silently dropping
    chat replies. We pin tasks to `app.state.background_tasks` and let the
    done-callback evict them when they finish.
    """
    background_tasks = getattr(app.state, "background_tasks", None)
    task = asyncio.create_task(
        _dispatch_chat_reply(
            runner=runner,
            cs_messenger=cs_messenger,
            openid=openid,
            user_text=user_text,
        )
    )
    if background_tasks is not None:
        background_tasks.add(task)
        task.add_done_callback(background_tasks.discard)


# ---------------------------------------------------------------------------
# WeChat endpoints
# ---------------------------------------------------------------------------


@router.get("/wechat")
async def wechat_verify(
    request: Request,
    signature: str = "",
    timestamp: str = "",
    nonce: str = "",
    echostr: str = "",
) -> Response:
    """WeChat server URL verification handshake (GET)."""
    token: str = getattr(request.app.state, "wechat_webhook_token", "")
    if not _verify_sha1(token, signature=signature, timestamp=timestamp, nonce=nonce):
        return PlainTextResponse("forbidden", status_code=403)
    return PlainTextResponse(echostr)


@router.post("/wechat")
async def wechat_message(
    request: Request,
    signature: str = "",
    timestamp: str = "",
    nonce: str = "",
) -> Response:
    """WeChat message callback (POST). Returns synchronous XML ack."""
    token: str = getattr(request.app.state, "wechat_webhook_token", "")
    if not _verify_sha1(token, signature=signature, timestamp=timestamp, nonce=nonce):
        return PlainTextResponse("forbidden", status_code=403)

    try:
        body = (await request.body()).decode("utf-8")
    except Exception:
        return PlainTextResponse("forbidden", status_code=403)

    msg = _parse_xml_text_message(body)

    runner = getattr(request.app.state, "agent_runner", None)
    cs_messenger = getattr(request.app.state, "wechat_cs_messenger", None)

    if runner is not None and cs_messenger is not None and msg is not None:
        openid = msg.get("FromUserName", "")
        user_text = msg.get("Content", "")[:_MAX_USER_TEXT_CHARS]
        if openid and user_text:
            _spawn_background_dispatch(
                app=request.app,
                runner=runner,
                cs_messenger=cs_messenger,
                openid=openid,
                user_text=user_text,
            )

    ack = "<xml><Content><![CDATA[success]]></Content></xml>"
    return Response(content=ack, media_type="application/xml")


# ---------------------------------------------------------------------------
# WeWork endpoints
# ---------------------------------------------------------------------------


@router.get("/wework")
async def wework_verify(
    request: Request,
    msg_signature: str = "",
    timestamp: str = "",
    nonce: str = "",
    echostr: str = "",
) -> Response:
    """WeWork server URL verification handshake (GET)."""
    token: str = getattr(request.app.state, "wework_webhook_token", "")
    if not _verify_sha1(
        token, signature=msg_signature, timestamp=timestamp, nonce=nonce
    ):
        return PlainTextResponse("forbidden", status_code=403)
    return PlainTextResponse(echostr)


@router.post("/wework")
async def wework_message(
    request: Request,
    msg_signature: str = "",
    timestamp: str = "",
    nonce: str = "",
) -> Response:
    """WeWork message callback (POST). Returns synchronous XML ack."""
    token: str = getattr(request.app.state, "wework_webhook_token", "")
    if not _verify_sha1(
        token, signature=msg_signature, timestamp=timestamp, nonce=nonce
    ):
        return PlainTextResponse("forbidden", status_code=403)

    try:
        body = (await request.body()).decode("utf-8")
    except Exception:
        return PlainTextResponse("forbidden", status_code=403)

    msg = _parse_xml_text_message(body)

    runner = getattr(request.app.state, "agent_runner", None)
    cs_messenger = getattr(request.app.state, "wework_cs_messenger", None)

    if runner is not None and cs_messenger is not None and msg is not None:
        openid = msg.get("FromUserName", "")
        user_text = msg.get("Content", "")[:_MAX_USER_TEXT_CHARS]
        if openid and user_text:
            _spawn_background_dispatch(
                app=request.app,
                runner=runner,
                cs_messenger=cs_messenger,
                openid=openid,
                user_text=user_text,
            )

    ack = "<xml><Content><![CDATA[success]]></Content></xml>"
    return Response(content=ack, media_type="application/xml")
