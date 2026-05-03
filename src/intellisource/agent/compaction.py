"""Conversation context LLM compaction.

Provides token-aware context compression for chat sessions using structured
LLM summarization. Tool outputs are pruned first (oldest-first) to protect
recency. Falls back to truncation when LLM is unavailable.
"""

from __future__ import annotations

import logging
from typing import Any

from intellisource.llm.model_config import ModelProfile
from intellisource.llm.prompt_builder import PromptBuilder

logger = logging.getLogger(__name__)

_PROTECTED_TOOL_COUNT = 3
_DEFAULT_CONTEXT_TOKEN_BUDGET = 2000


def _total_tokens(
    messages: list[dict[str, Any]],
    gateway: Any,
    model: str,
) -> int:
    """Return total estimated token count for all messages."""
    return sum(gateway.estimate_tokens(m.get("content", ""), model) for m in messages)


def needs_compaction(
    messages: list[dict[str, Any]],
    gateway: Any,
    profile: ModelProfile,
    context_token_budget: int = _DEFAULT_CONTEXT_TOKEN_BUDGET,
    model: str = "gpt-4o-mini",
) -> bool:
    """Return True when messages exceed the auto-trigger threshold.

    Threshold = min(context_window * 0.8, context_token_budget).
    Both constraints must be satisfied: the model capacity upper bound
    (80 % of context window) and the system configuration upper bound
    (context_token_budget).

    Args:
        messages: Current message list.
        gateway: LLM gateway providing estimate_tokens().
        profile: ModelProfile for the active model.
        context_token_budget: System-level token budget (arch §5.1 [chat]).
        model: Model identifier passed to estimate_tokens.

    Returns:
        True if compaction should be triggered.
    """
    if not messages:
        return False
    threshold = min(int(profile.context_window * 0.8), context_token_budget)
    estimated = _total_tokens(messages, gateway, model)
    return estimated > threshold


def _prune_old_tool_messages(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Remove tool messages older than the last _PROTECTED_TOOL_COUNT.

    Locates all role=tool messages in the list and removes those that are
    not among the most recent _PROTECTED_TOOL_COUNT tool messages.

    Args:
        messages: Full message list to prune.

    Returns:
        New message list with old tool messages removed.
    """
    tool_indices = [i for i, m in enumerate(messages) if m.get("role") == "tool"]
    protected_indices = set(tool_indices[-_PROTECTED_TOOL_COUNT:])
    removable_indices = set(tool_indices) - protected_indices
    return [m for i, m in enumerate(messages) if i not in removable_indices]


def _build_summary_prompt(messages: list[dict[str, Any]]) -> str:
    """Render the compaction_summary template with conversation history.

    Args:
        messages: Messages to summarize.

    Returns:
        Formatted prompt string.
    """
    conversation_history = "\n".join(
        f"{m.get('role', 'unknown')}: {m.get('content', '')}" for m in messages
    )
    builder = PromptBuilder("compaction_summary")
    builder.add_context("conversation_history", conversation_history)
    return builder.build()


def _truncation_fallback(
    messages: list[dict[str, Any]],
    gateway: Any,
    profile: ModelProfile,
    model: str,
) -> list[dict[str, Any]]:
    """Keep the most recent messages that fit within context_window * 0.6.

    Iterates from the most recent message backwards, accumulating messages
    until the token budget (context_window * 0.6) is exhausted.

    Args:
        messages: Full message list.
        gateway: LLM gateway providing estimate_tokens().
        profile: ModelProfile for token limit reference.
        model: Model identifier passed to estimate_tokens.

    Returns:
        Subset of messages (most recent) fitting the budget.
    """
    target_tokens = int(profile.context_window * 0.6)
    kept: list[dict[str, Any]] = []
    used = 0
    for msg in reversed(messages):
        cost = gateway.estimate_tokens(msg.get("content", ""), model)
        if used + cost > target_tokens and kept:
            break
        kept.append(msg)
        used += cost
    return list(reversed(kept)) if kept else messages[-1:]


async def compact_messages(
    messages: list[dict[str, Any]],
    gateway: Any,
    profile: ModelProfile,
    context_token_budget: int = _DEFAULT_CONTEXT_TOKEN_BUDGET,
    model: str = "gpt-4o-mini",
) -> list[dict[str, Any]]:
    """Compact conversation messages using token-aware LLM summarization.

    Compression pipeline:
      1. Check whether total tokens exceed the auto-trigger threshold.
         If not, return messages unchanged.
      2. Prune old tool messages (role=tool), protecting the last
         _PROTECTED_TOOL_COUNT tool results.
      3. If still over threshold, call LLM to produce a structured summary
         (using compaction_summary.txt template) replacing the pruned block.
      4. On LLM failure, fall back to truncation: keep the most recent
         messages that fit within context_window * 0.6 tokens.

    Args:
        messages: Full conversation message list.
        gateway: LLM gateway providing estimate_tokens() and complete().
        profile: ModelProfile for the active model (provides context_window).
        context_token_budget: System-level budget from config.chat
            (arch §5.1, default 2000).
        model: Model identifier used for token estimation.

    Returns:
        Compacted message list.  Token count <= context_window * 0.6
        after successful summarization.
    """
    if not messages:
        return []

    total = _total_tokens(messages, gateway, model)
    threshold = min(int(profile.context_window * 0.8), context_token_budget)
    if total <= threshold:
        return list(messages)

    # Step 1: prune old tool messages
    pruned = _prune_old_tool_messages(messages)

    # Step 2: attempt LLM summarization
    # Build prompt outside try-block so infrastructure failures (e.g.
    # FileNotFoundError from a missing template) propagate rather than
    # silently falling back to truncation.
    target_tokens = int(profile.context_window * 0.6)
    prompt = _build_summary_prompt(pruned)
    try:
        llm_result = await gateway.complete(prompt)
        summary_text = str(llm_result.content)

        summary_msg: dict[str, Any] = {"role": "system", "content": summary_text}

        # Keep most recent messages that fit alongside the summary
        summary_cost = gateway.estimate_tokens(summary_text, model)
        remaining_budget = max(0, target_tokens - summary_cost)

        recent: list[dict[str, Any]] = []
        used = 0
        for msg in reversed(pruned):
            cost = gateway.estimate_tokens(msg.get("content", ""), model)
            if used + cost > remaining_budget:
                break
            recent.append(msg)
            used += cost
        recent = list(reversed(recent))

        return [summary_msg, *recent]

    except Exception as exc:
        # Catch-all for LLM-side failures: LLMError (intellisource-wrapped),
        # litellm-native exceptions (RateLimitError, APIConnectionError, etc.
        # which subclass OpenAIError → Exception, not LLMError/RuntimeError),
        # plus malformed responses. Infrastructure failures from prompt build
        # (e.g. missing template) already propagate from outside the try block.
        logger.warning("LLM summarization failed, using truncation fallback: %s", exc)
        return _truncation_fallback(messages, gateway, profile, model)
