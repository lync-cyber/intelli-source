"""Webhooks router for WeChat and WeWork inbound message callbacks (AC-5/6/9/11/12)."""

from __future__ import annotations

import asyncio
import hashlib
import xml.etree.ElementTree as ET
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import PlainTextResponse

from intellisource.agent.response_utils import extract_answer
from intellisource.api.chat_sessions import MAX_HISTORY_TURNS
from intellisource.api.webhook_crypto import WeComCrypto, WeComCryptoError
from intellisource.observability.logging import get_logger
from intellisource.pipeline.definition_service import load_pipeline_config

logger = get_logger(__name__)

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


async def _load_cs_session(
    db_manager: Any, channel: str, openid: str
) -> tuple[Any, list[dict[str, Any]]]:
    """Return (session_id, prior messages) for a channel+user pair, else (None, [])."""
    if db_manager is None:
        return None, []
    from intellisource.storage.repositories.chat_session import ChatSessionRepository

    try:
        async with db_manager.get_session() as db_session:
            stored = await ChatSessionRepository(db_session).find_by_channel_user(
                channel, openid
            )
            if stored is None:
                return None, []
            messages = (stored.context or {}).get("messages")
            history = list(messages) if isinstance(messages, list) else []
            return stored.id, history[-(MAX_HISTORY_TURNS * 2) :]
    except Exception:
        logger.exception("CS session load failed for channel=%s", channel)
        return None, []


async def _persist_cs_turn(
    db_manager: Any,
    channel: str,
    openid: str,
    session_id: Any,
    prior_messages: list[dict[str, Any]],
    user_text: str,
    answer: str,
) -> None:
    """Append the user+assistant turn to the channel+user session (best-effort)."""
    if db_manager is None:
        return
    new_messages = (
        prior_messages
        + [
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": answer},
        ]
    )[-(MAX_HISTORY_TURNS * 2) :]
    from intellisource.storage.repositories.chat_session import ChatSessionRepository

    try:
        async with db_manager.get_session() as db_session:
            repo = ChatSessionRepository(db_session)
            if session_id is not None:
                await repo.update_context(session_id, {"messages": new_messages})
            else:
                await repo.create(
                    channel=channel,
                    channel_user_id=openid,
                    context={"messages": new_messages},
                )
    except Exception:
        logger.exception("CS session persist failed for channel=%s", channel)


async def _dispatch_chat_reply(
    app: Any,
    runner: Any,
    cs_messenger: Any,
    channel: str,
    openid: str,
    user_text: str,
) -> None:
    """Resolve the channel+user session, run the agent, persist the turn, reply."""
    db_manager = getattr(app.state, "db", None)
    try:
        config = load_pipeline_config("instant-search")
        session_id, prior_messages = await _load_cs_session(db_manager, channel, openid)
        session_payload: dict[str, Any] = {}
        if prior_messages:
            session_payload["messages"] = prior_messages
        flex_result = await runner.run_flexible(
            config,
            user_message=user_text,
            session=session_payload,
        )
        answer = extract_answer(flex_result)
        if not answer:
            answer = _FALLBACK_TEXT
        await _persist_cs_turn(
            db_manager, channel, openid, session_id, prior_messages, user_text, answer
        )
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
    channel: str,
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
            app=app,
            runner=runner,
            cs_messenger=cs_messenger,
            channel=channel,
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
                channel="wechat",
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
    crypto: WeComCrypto | None = getattr(request.app.state, "wecom_crypto", None)
    if crypto is None:
        return PlainTextResponse("service unavailable", status_code=503)
    try:
        echo_plain = crypto.verify_url(msg_signature, timestamp, nonce, echostr)
    except WeComCryptoError:
        logger.warning("WeWork verify_url failed", exc_info=True)
        return PlainTextResponse("forbidden", status_code=401)
    return PlainTextResponse(echo_plain)


@router.post("/wework")
async def wework_message(
    request: Request,
    msg_signature: str = "",
    timestamp: str = "",
    nonce: str = "",
) -> Response:
    """WeWork message callback (POST). Returns synchronous XML ack."""
    crypto: WeComCrypto | None = getattr(request.app.state, "wecom_crypto", None)
    if crypto is None:
        return PlainTextResponse("service unavailable", status_code=503)

    try:
        raw_body = (await request.body()).decode("utf-8")
    except Exception:
        return PlainTextResponse("forbidden", status_code=401)

    try:
        plain_xml = crypto.decrypt_message(msg_signature, timestamp, nonce, raw_body)
    except WeComCryptoError:
        logger.warning("WeWork decrypt_message failed", exc_info=True)
        return PlainTextResponse("forbidden", status_code=401)

    msg = _parse_xml_text_message(plain_xml)

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
                channel="wework",
                openid=openid,
                user_text=user_text,
            )

    ack = "<xml><Content><![CDATA[success]]></Content></xml>"
    return Response(content=ack, media_type="application/xml")
