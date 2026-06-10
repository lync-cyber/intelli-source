"""CompactionMixin: token estimation + agent-history compaction for LLMGateway."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import litellm

if TYPE_CHECKING:
    from intellisource.llm.gateway._proto import _GatewayProto


class _CompactionMixin:
    """Token-aware sizing and agent-history summarisation.

    Groups the token estimator with the compaction entry point that consumes
    it: the agent loop tracks a running estimate via ``estimate_history_tokens``
    and feeds it back as ``precomputed_total`` so the compactor skips a per-turn
    full scan.
    """

    def estimate_tokens(self: _GatewayProto, text: str, model: str) -> int:
        """Estimate token count for text.

        Prefers ``litellm.token_counter``; falls back to ``len(text)//4``.
        """
        try:
            count = litellm.token_counter(model=model, text=text)
            if isinstance(count, int):
                return count
            return len(text) // 4
        except Exception:
            return len(text) // 4

    def estimate_history_tokens(
        self: _GatewayProto,
        messages: list[dict[str, Any]],
        task_type: str = "chat",
    ) -> int:
        """Sum the estimated token count of every message under ``task_type``.

        Resolves the active model the same way :meth:`compress_if_needed` does so
        the agent loop can maintain a running total on the identical basis and
        feed it back as ``precomputed_total``.
        """
        model = str(self._model_routing.get_model(task_type).get("model", ""))
        return sum(self.estimate_tokens(m.get("content", ""), model) for m in messages)

    async def compress_if_needed(
        self: _GatewayProto,
        messages: list[dict[str, Any]],
        task_type: str = "chat",
        precomputed_total: int | None = None,
    ) -> list[dict[str, Any]]:
        """Summarise old turns once the history passes the agent compaction budget.

        Resolves the active model/profile for ``task_type`` and delegates to the
        pairing-safe :func:`compact_agent_messages`; a sub-threshold history is
        returned unchanged. The trigger is the smaller of half the context window
        and ``_AGENT_COMPACT_TRIGGER_TOKENS`` — a bare half-window of a 1M-token
        model never fires before a run hits its own budget. Keeps the agent loop
        from reaching into gateway internals (model routing, window table).
        """
        from intellisource.llm.compaction import (
            _AGENT_COMPACT_TRIGGER_TOKENS,
            compact_agent_messages,
        )
        from intellisource.llm.model_config import ModelProfile

        model = str(self._model_routing.get_model(task_type).get("model", ""))
        profile = self._model_routing.get_profile(model)
        if profile is None:
            window = self._CONTEXT_WINDOWS.get(model, self._DEFAULT_CONTEXT_WINDOW)
            profile = ModelProfile(
                temperature=0.0,
                max_tokens=self._default_max_tokens,
                context_window=window,
            )
        trigger = min(int(profile.context_window * 0.5), _AGENT_COMPACT_TRIGGER_TOKENS)
        return await compact_agent_messages(
            messages,
            gateway=self,
            profile=profile,
            context_token_budget=trigger,
            model=model,
            precomputed_total=precomputed_total,
        )
