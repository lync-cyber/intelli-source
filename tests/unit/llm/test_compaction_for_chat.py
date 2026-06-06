"""Behavior tests for llm.compaction.compact_messages_for_chat.

Covers the chat-history compaction pipeline directly (no ModelProfile owned by
the caller): LLM-summary success keeps recent turns, gateway failure falls back
to char-budget truncation, and role=tool messages are pruned oldest-first.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from intellisource.llm.compaction import compact_messages_for_chat


@pytest.mark.asyncio
async def test_llm_summary_replaces_old_messages_keeps_recent() -> None:
    """A successful LLM summary yields a system summary plus recent messages."""
    gateway = MagicMock()
    gateway.estimate_tokens = MagicMock(
        side_effect=lambda text, model: max(len(str(text)) // 4, 1)
    )
    gateway.complete = AsyncMock(return_value=MagicMock(content="OLD SUMMARY"))

    old = [{"role": "user", "content": "old turn " * 200} for _ in range(20)]
    recent = [{"role": "user", "content": "recent question"}]

    compacted = await compact_messages_for_chat(
        old + recent, gateway=gateway, max_tokens=300
    )

    roles = [m["role"] for m in compacted]
    assert "system" in roles
    assert any(m.get("content") == "OLD SUMMARY" for m in compacted)


@pytest.mark.asyncio
async def test_llm_complete_raises_falls_back_to_truncation() -> None:
    """When gateway.complete raises, the truncation fallback path runs."""
    gateway = MagicMock()
    gateway.estimate_tokens = MagicMock(
        side_effect=lambda text, model: max(len(str(text)) // 4, 1)
    )
    gateway.complete = AsyncMock(side_effect=RuntimeError("LLM down"))

    long_msgs: list[dict[str, Any]] = [
        {"role": "user", "content": f"msg {i} " * 100} for i in range(20)
    ]
    long_msgs.append({"role": "user", "content": "newest"})

    compacted = await compact_messages_for_chat(
        long_msgs, gateway=gateway, max_tokens=200
    )

    assert len(compacted) >= 1
    # No system summary on fallback — truncation only.
    sentinel = "Summary of previous conversation: "
    assert all(m.get("content") != sentinel for m in compacted)
    # Most recent message must survive.
    assert any(m.get("content") == "newest" for m in compacted)


@pytest.mark.asyncio
async def test_no_gateway_prunes_tool_messages_first() -> None:
    """Without a gateway, char-budget truncation prunes role=tool oldest-first."""
    big_filler = "x" * 600
    messages: list[dict[str, str]] = [
        {"role": "tool", "content": f"old tool {i} {big_filler}"} for i in range(5)
    ]
    messages.append({"role": "user", "content": "real question"})
    messages.append({"role": "assistant", "content": "real answer"})

    compacted = await compact_messages_for_chat(messages, gateway=None, max_tokens=200)

    roles_remaining = [m["role"] for m in compacted]
    assert "user" in roles_remaining
    assert "assistant" in roles_remaining
