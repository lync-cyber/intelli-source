"""Shared ChatSession persistence for conversational endpoints.

Hydrates prior turns into the run session payload and writes the new
user+assistant turn back, so ``/search/chat`` and ``/agent/chat`` share one
multi-turn memory implementation (compaction included). All DB work is
best-effort: a missing DB or a transaction error is logged, never raised, so
the chat reply path stays usable even without persistence.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from intellisource.core.settings import get_settings
from intellisource.llm.compaction import compact_messages_for_chat
from intellisource.observability.logging import get_logger

logger = get_logger(__name__)

CHAT_CHANNEL_API: str = "api"
MAX_HISTORY_TURNS: int = 10
_CHARS_PER_TOKEN: int = 4


def _compact_token_budget() -> int:
    """Effective chat-history compaction budget (IS_CHAT_COMPACT_TOKEN_BUDGET)."""
    return get_settings().chat_compact_token_budget


def _estimate_tokens(messages: list[dict[str, Any]]) -> int:
    """Estimate token count from messages (approx 1 token per 4 chars)."""
    total_chars = sum(len(m.get("content", "")) for m in messages)
    return total_chars // _CHARS_PER_TOKEN


async def _bounded_history(
    history: list[dict[str, Any]],
    gateway: Any,
    budget: int,
) -> list[dict[str, Any]]:
    """Return the history to persist, bounded by *budget* tokens.

    Under budget the history is returned unchanged. Over budget it is
    token-aware compacted into ``[summary, ...recent]`` so older turns survive
    as a structured summary rather than being hard-sliced away. With no gateway
    the compaction helper degrades to char-budget truncation; never raises.
    """
    if _estimate_tokens(history) <= budget:
        return history
    return await compact_messages_for_chat(history, gateway=gateway, max_tokens=budget)


async def prepare_session(
    *,
    db_manager: Any,
    llm_gateway: Any,
    session_id: str | None,
    base_session: dict[str, Any] | None,
    max_tokens_budget: int | None,
) -> tuple[Any, uuid.UUID | None, dict[str, Any]]:
    """Load the stored ChatSession (if any) and build the run session payload.

    Returns ``(stored_session, session_uuid, session_payload)``. The payload's
    ``messages`` are the (compacted) prior turns the agent loop replays; an
    explicit ``base_session['messages']`` from the caller takes precedence and
    suppresses history hydration.
    """
    stored_session: Any = None
    session_uuid: uuid.UUID | None = None
    session_payload: dict[str, Any] = dict(base_session or {})

    if db_manager is not None and session_id:
        try:
            async with db_manager.get_session() as db_session:
                stored_session, session_uuid = await _load_chat_session(
                    db_session, session_id
                )
        except Exception:
            logger.exception("ChatSession lookup transaction failed")

    if stored_session is not None:
        history_messages = (stored_session.context or {}).get("messages")
        if isinstance(history_messages, list) and "messages" not in session_payload:
            compacted = await compact_history(
                llm_gateway, stored_session, history_messages, max_tokens_budget
            )
            session_payload["messages"] = compacted[-MAX_HISTORY_TURNS:]

    return stored_session, session_uuid, session_payload


async def persist_turn(
    db_manager: Any,
    *,
    stored_session: Any,
    session_uuid: uuid.UUID | None,
    user_message: str,
    assistant_answer: str,
    llm_gateway: Any = None,
    max_tokens_budget: int | None = None,
) -> uuid.UUID:
    """Persist one user+assistant turn in its own DB transaction; return its id.

    When the appended history exceeds the token budget it is token-aware
    compacted into ``[summary, ...recent]`` before persistence, so older context
    survives as a structured summary in the stored row. When no DB is configured
    the turn is not written but a fresh session id is still returned, so the
    response always carries a usable session token. DB errors are logged, never
    raised.
    """
    response_session_uuid = session_uuid or uuid.uuid4()
    if db_manager is None:
        return response_session_uuid
    budget = max_tokens_budget or _compact_token_budget()
    try:
        async with db_manager.get_session() as db_session:
            response_session_uuid = await _persist_chat_turn(
                db_session,
                existing=stored_session,
                session_id=response_session_uuid,
                user_message=user_message,
                assistant_answer=assistant_answer,
                llm_gateway=llm_gateway,
                budget=budget,
            )
    except Exception:
        logger.exception("ChatSession persist transaction failed")
    return response_session_uuid


async def _load_chat_session(
    db_session: AsyncSession, session_id: str | None
) -> tuple[Any, uuid.UUID | None]:
    """Return (ChatSession row or None, parsed UUID or None) for *session_id*."""
    if not session_id:
        return None, None
    try:
        session_uuid = uuid.UUID(session_id)
    except ValueError:
        return None, None

    from intellisource.storage.repositories.chat_session import ChatSessionRepository

    try:
        row = await ChatSessionRepository(db_session).get_by_id(session_uuid)
    except Exception:
        logger.exception("ChatSession lookup failed for session_id=%s", session_id)
        return None, session_uuid
    return row, session_uuid


async def _persist_chat_turn(
    db_session: AsyncSession,
    *,
    existing: Any,
    session_id: uuid.UUID,
    user_message: str,
    assistant_answer: str,
    llm_gateway: Any = None,
    budget: int,
) -> uuid.UUID:
    """Append the new user+assistant turn to ChatSession.context.messages.

    Creates a new row when *existing* is None, using *session_id* as both the
    primary key and API channel_user_id so the response token loads the same
    row on the next request. The appended history is bounded by token budget
    (summarised over budget) so the stored row stays self-bounded and older
    context survives as a summary. DB errors are logged but never raised.
    """
    from intellisource.storage.repositories.chat_session import ChatSessionRepository

    new_messages = [
        {"role": "user", "content": user_message},
        {"role": "assistant", "content": assistant_answer},
    ]
    repo = ChatSessionRepository(db_session)
    try:
        if existing is not None:
            context = dict(existing.context or {})
            history = list(context.get("messages") or [])
            history.extend(new_messages)
            context["messages"] = await _bounded_history(history, llm_gateway, budget)
            await repo.update_context(existing.id, context)
            session_id = existing.id
        else:
            await repo.create(
                id=session_id,
                channel=CHAT_CHANNEL_API,
                channel_user_id=str(session_id),
                context={"messages": new_messages},
            )
        await db_session.commit()
    except Exception:
        logger.exception("ChatSession persist failed; rolling back")
        try:
            await db_session.rollback()
        except Exception:
            logger.exception("ChatSession rollback also failed")
    return session_id


async def compact_history(
    llm_gateway: Any,
    stored_session: Any,
    history_messages: list[dict[str, Any]],
    max_tokens_budget: int | None,
) -> list[dict[str, Any]]:
    """Compact stored chat history before replay; pure, returns a new list.

    A history over the token budget is LLM-summarized (or truncated when no
    gateway is configured) via ``llm.compaction.compact_messages_for_chat``
    instead of hard-sliced, so older context survives. The detached
    ``stored_session.context`` is never written, so the persist path reads the
    untouched DB history rather than this read-side compaction result. Falls
    back to the raw history on any error.
    """
    budget = max_tokens_budget or _compact_token_budget()
    try:
        messages: list[dict[str, Any]] = stored_session.context["messages"]
        if _estimate_tokens(messages) <= budget:
            return messages
        return await compact_messages_for_chat(
            messages, gateway=llm_gateway, max_tokens=budget
        )
    except Exception:
        logger.exception("chat history compaction failed; using raw history")
        return history_messages
