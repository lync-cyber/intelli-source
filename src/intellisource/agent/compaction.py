"""Conversation context LLM compaction.

Provides token-aware context compression for chat sessions using structured
LLM summarization. Tool outputs are pruned first (oldest-first) to protect
recency. Falls back to truncation when LLM is unavailable.

The standalone compaction utilities live in ``intellisource.llm.compaction``.
This module re-exports them for backward compatibility.
"""

from __future__ import annotations

from intellisource.llm.compaction import (
    _DEFAULT_CONTEXT_TOKEN_BUDGET as _DEFAULT_CONTEXT_TOKEN_BUDGET,
)
from intellisource.llm.compaction import (
    _build_summary_prompt as _build_summary_prompt,
)
from intellisource.llm.compaction import (
    _prune_old_tool_messages as _prune_old_tool_messages,
)
from intellisource.llm.compaction import (
    _total_tokens as _total_tokens,
)
from intellisource.llm.compaction import (
    _truncation_fallback as _truncation_fallback,
)
from intellisource.llm.compaction import (
    _truncation_fallback_no_gateway as _truncation_fallback_no_gateway,
)
from intellisource.llm.compaction import (
    compact_messages as compact_messages,
)
from intellisource.llm.compaction import (
    compact_messages_for_chat as compact_messages_for_chat,
)
from intellisource.llm.compaction import (
    needs_compaction as needs_compaction,
)
from intellisource.observability.logging import get_logger

logger = get_logger(__name__)

_PROTECTED_TOOL_COUNT = 3

__all__ = [
    "compact_messages",
    "compact_messages_for_chat",
    "needs_compaction",
    "_prune_old_tool_messages",
    "_build_summary_prompt",
    "_truncation_fallback",
    "_truncation_fallback_no_gateway",
    "_DEFAULT_CONTEXT_TOKEN_BUDGET",
]
