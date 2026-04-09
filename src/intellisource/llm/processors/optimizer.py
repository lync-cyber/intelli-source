"""PushOptimizer: push content optimization processor.

Uses LLM to optimize content for distribution channels by adjusting
tone, length, and format based on channel-specific requirements.
"""

from __future__ import annotations

import json
from typing import Any

from intellisource.llm.processors._async_compat import run_async
from intellisource.llm.prompts import load_prompt
from intellisource.pipeline.base import BaseProcessor
from intellisource.pipeline.context import PipelineContext


class PushOptimizer(BaseProcessor):
    """Optimize content for push distribution using LLM.

    Adapts content presentation (title, summary, format) based on
    the target distribution channel's constraints and preferences.
    """

    def __init__(self, gateway: Any, call_log: Any) -> None:
        self._gateway = gateway
        self._call_log = call_log

    def process(self, context: PipelineContext) -> PipelineContext:
        """Optimize content for the target push channel.

        Args:
            context: Pipeline context with title, body_text, and
                     optional push_channel.

        Returns:
            Updated context with optimized_title and optimized_summary.
        """
        title = context.get("title", "")
        body_text = context.get("body_text", "")
        channel = context.get("push_channel", "default")

        optimized = self._try_llm_optimize(title, body_text, channel)
        if optimized is None:
            optimized = self._truncation_fallback(title, body_text)

        context.set("optimized_title", optimized.get("title", title))
        context.set("optimized_summary", optimized.get("summary", ""))
        return context

    def _try_llm_optimize(
        self,
        title: str,
        body_text: str,
        channel: str,
    ) -> dict[str, str] | None:
        """Attempt LLM-based content optimization."""
        try:
            prompt = load_prompt(
                "optimizer", channel=channel, title=title, body_text=body_text
            )
            result = run_async(self._gateway.complete(prompt))
            run_async(
                self._call_log.record(
                    call_type="optimize",
                    status="success",
                    input_tokens=result.metadata.get("input_tokens", 0),
                    output_tokens=result.metadata.get("output_tokens", 0),
                    metadata=result.metadata,
                )
            )
            parsed = json.loads(result.content)
            if isinstance(parsed, dict) and "title" in parsed and "summary" in parsed:
                return {
                    "title": str(parsed["title"]),
                    "summary": str(parsed["summary"]),
                }
            return None
        except Exception:
            return None

    @staticmethod
    def _truncation_fallback(title: str, body_text: str) -> dict[str, str]:
        """Fallback: truncate content to reasonable push lengths."""
        max_title_len = 80
        max_summary_len = 200
        opt_title = title[:max_title_len] if len(title) > max_title_len else title
        sentences = body_text.split(". ")
        summary = ". ".join(sentences[:3])
        if len(summary) > max_summary_len:
            summary = summary[:max_summary_len].rsplit(" ", 1)[0] + "..."
        return {"title": opt_title, "summary": summary}
