"""Conversation context LLM compaction.

Provides LLM-based context compression for chat sessions, replacing
the simple string-truncation approach with semantic summarization.

[ASSUMPTION] Currently delegates to LLM gateway for summarization.
Future versions may integrate specialized compaction models.
"""

from __future__ import annotations

from typing import Any

from intellisource.llm.prompts import load_prompt

_MAX_SUMMARY_PARTS = 20
_SUMMARY_CONTENT_LIMIT = 200


async def compact_messages(
    messages: list[dict[str, str]],
    gateway: Any,
    max_tokens: int,
) -> list[dict[str, str]]:
    """Compact old messages into a summary using LLM.

    Splits messages into old (to summarize) and recent (to keep),
    then uses the LLM gateway to produce a semantic summary of the
    old messages. Falls back to string truncation if LLM fails.

    Args:
        messages: Full list of conversation messages.
        gateway: LLM gateway with an async ``complete()`` method.
        max_tokens: Target token budget for the compacted context.

    Returns:
        Compacted message list with a system summary + recent messages.
    """
    keep_count = min(max(2, len(messages) // 10), len(messages))
    old_messages = messages[:-keep_count] if keep_count < len(messages) else []
    recent_messages = messages[-keep_count:]

    if not old_messages:
        return list(recent_messages)

    summary_text = await _llm_summarize(old_messages, gateway)

    return [
        {"role": "system", "content": summary_text},
        *recent_messages,
    ]


async def _llm_summarize(
    messages: list[dict[str, str]],
    gateway: Any,
) -> str:
    """Summarize messages using LLM gateway, with truncation fallback."""
    conversation_text = "\n".join(
        f"{msg['role']}: {msg['content'][:_SUMMARY_CONTENT_LIMIT]}"
        for msg in messages[:_MAX_SUMMARY_PARTS]
    )

    try:
        prompt = load_prompt("context_compress", conversation=conversation_text)
        result = await gateway.complete(prompt)
        return str(result.content)
    except Exception:
        # Fallback to simple string concatenation
        summary_parts = [
            f"{msg['role']}: {msg['content'][:_SUMMARY_CONTENT_LIMIT]}"
            for msg in messages[:_MAX_SUMMARY_PARTS]
        ]
        return "Summary of previous conversation: " + "; ".join(summary_parts)
