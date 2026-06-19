"""Token-aware conversation compaction utilities.

Provides message compaction for chat sessions using structured LLM summarization.
Tool outputs are pruned first (oldest-first) to protect recency. Falls back to
truncation when LLM is unavailable.

Both ``agent`` and ``search`` layers depend on this module; it must not import
from either of them.
"""

from __future__ import annotations

from typing import Any

from intellisource.llm.model_config import ModelProfile
from intellisource.llm.prompt_builder import PromptBuilder
from intellisource.observability.logging import get_logger

logger = get_logger(__name__)

_PROTECTED_TOOL_COUNT = 3
# Library fallback only — every caller passes an explicit budget. Chat callers
# resolve theirs from IS_CHAT_COMPACT_TOKEN_BUDGET; the agent loop passes a
# context-window-derived trigger.
_DEFAULT_CONTEXT_TOKEN_BUDGET = 2000
_AGENT_PROTECT_LAST_N = 20
# Absolute token budget that triggers agent-history compaction. A fraction of a
# model's context window (e.g. 0.5 * 1M) never fires before a run hits its own
# token budget, so the head is summarised once the working history passes this
# fixed ceiling instead.
_AGENT_COMPACT_TRIGGER_TOKENS = 48000


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
        context_token_budget: Compaction budget supplied by the caller.
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
        context_token_budget: Compaction budget supplied by the caller.
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


def _truncation_fallback_no_gateway(
    messages: list[dict[str, Any]],
    max_tokens: int,
) -> list[dict[str, Any]]:
    """Truncate by character estimate when no gateway is available.

    Approximates token cost as ``len(content) // 4`` (industry standard)
    and keeps the most recent messages that fit within ``max_tokens``.
    role=tool messages are pruned first (oldest-first) before truncation.
    """
    pruned = _prune_old_tool_messages(messages)
    target_chars = max_tokens * 4
    kept: list[dict[str, Any]] = []
    used = 0
    for msg in reversed(pruned):
        cost = len(str(msg.get("content", "")))
        if used + cost > target_chars and kept:
            break
        kept.append(msg)
        used += cost
    return list(reversed(kept)) if kept else pruned[-1:] if pruned else []


def _safe_cut_points(messages: list[dict[str, Any]]) -> list[int]:
    """Indices ``i`` where ``messages[i:]`` is a self-contained valid suffix.

    A cut is safe only when no tool_call is still open entering ``i`` (every
    prior assistant ``tool_calls`` already has its ``tool`` responses) and the
    message at ``i`` opens a fresh turn (``user`` / ``assistant``). Cutting here
    never separates an assistant ``tool_calls`` message from its responses.
    """
    cuts: list[int] = []
    open_ids: set[str] = set()
    for idx, message in enumerate(messages):
        role = message.get("role")
        if not open_ids and role in {"user", "assistant"}:
            cuts.append(idx)
        if role == "tool":
            open_ids.discard(str(message.get("tool_call_id", "")))
        elif role == "assistant":
            for tool_call in message.get("tool_calls") or []:
                tid = str(tool_call.get("id", ""))
                if tid:
                    open_ids.add(tid)
    return cuts


async def compact_agent_messages(
    messages: list[dict[str, Any]],
    gateway: Any,
    profile: ModelProfile,
    *,
    protect_last_n: int = _AGENT_PROTECT_LAST_N,
    context_token_budget: int = _DEFAULT_CONTEXT_TOKEN_BUDGET,
    model: str = "gpt-4o-mini",
    precomputed_total: int | None = None,
) -> list[dict[str, Any]]:
    """Compact an agent message list while preserving tool-call pairing.

    Unlike :func:`compact_messages` (built for plain chat history), this keeps
    assistant ``tool_calls`` messages bound to their ``tool`` responses: the cut
    between the summarised head and the protected tail is snapped back to a safe
    boundary, so the result always passes the agent loop's history invariant.

    ``precomputed_total`` lets a caller that already tracks a running token
    estimate skip the full per-call :func:`_total_tokens` scan.
    """
    if not messages:
        return []

    total = (
        precomputed_total
        if precomputed_total is not None
        else _total_tokens(messages, gateway, model)
    )
    threshold = min(int(profile.context_window * 0.8), context_token_budget)
    if total <= threshold:
        return list(messages)

    # Preserve a leading system prompt verbatim; summarise/cut only the body.
    body_start = 1 if messages[0].get("role") == "system" else 0
    head = messages[:body_start]

    # Snap the protect-last-N target back to the nearest safe boundary so an
    # assistant tool_calls message is never separated from its tool responses.
    target = max(body_start, len(messages) - protect_last_n)
    cut = body_start
    for candidate in _safe_cut_points(messages):
        if body_start <= candidate <= target:
            cut = candidate
    if cut <= body_start:
        # No safe boundary to summarise behind (e.g. one long open chain).
        return list(messages)

    summarised = messages[body_start:cut]
    tail = messages[cut:]
    prompt = _build_summary_prompt(summarised)
    try:
        llm_result = await gateway.complete(prompt)
        summary_text = str(llm_result.content)
    except Exception as exc:
        logger.warning("agent summarization failed, dropping old turns: %s", exc)
        summary_text = ""
    summary_msg: dict[str, Any] = {
        "role": "system",
        "content": summary_text or "(earlier conversation omitted)",
    }
    return [*head, summary_msg, *tail]


def _chat_compaction_context_window(max_tokens: int) -> int:
    """Synthetic ``context_window`` for the profile-less chat compaction path.

    Sized so the pipeline's recent-keep budget (``0.6 * window``) and trigger
    threshold (``min(0.8 * window, max_tokens)``) both land at ``max_tokens``,
    so the compacted result fits within the budget and does not re-cross the
    threshold on the next turn. ``-(-x // y)`` is integer ceil so the budget is
    never rounded down.
    """
    return -(-max_tokens * 10 // 6)


async def compact_messages_for_chat(
    messages: list[dict[str, Any]],
    gateway: Any,
    max_tokens: int = _DEFAULT_CONTEXT_TOKEN_BUDGET,
    model: str = "gpt-4o-mini",
) -> list[dict[str, Any]]:
    """Compact chat session messages without requiring a ModelProfile.

    Convenience wrapper for callers (e.g. ``api/chat_sessions.py``) that
    do not own a ModelProfile but need the same token-aware pruning and
    LLM-summarization pipeline as ``compact_messages``. A synthetic
    ModelProfile is constructed from ``max_tokens`` so the existing pipeline
    treats it as the budget upper bound; pruning, summarization and the
    truncation fallback all behave identically to ``compact_messages``.

    The synthetic ``context_window`` is sized so the pipeline's recent-keep
    budget (``context_window * 0.6``) and trigger threshold
    (``min(context_window * 0.8, max_tokens)``) both land at ``max_tokens``.
    The compacted result therefore fits within ``max_tokens`` and does not
    immediately re-cross the threshold on the next turn.

    Args:
        messages: Full conversation message list.
        gateway: LLM gateway (may be ``None`` — caller falls back to
            local truncation in that case, callers are expected to check).
        max_tokens: Token budget for the compacted result.
        model: Model identifier used for token estimation.

    Returns:
        Compacted message list with old tool messages pruned first and
        an LLM-generated summary replacing the oldest block when
        summarization succeeds.
    """
    if gateway is None:
        return _truncation_fallback_no_gateway(messages, max_tokens)

    profile = ModelProfile(
        temperature=0.0,
        max_tokens=max_tokens,
        context_window=_chat_compaction_context_window(max_tokens),
    )
    return await compact_messages(
        messages,
        gateway=gateway,
        profile=profile,
        context_token_budget=max_tokens,
        model=model,
    )
