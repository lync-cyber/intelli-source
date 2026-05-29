"""LLM-based summarizer factory for the agent layer.

Provides a pre-built async callable that combines the LLM gateway with
the structured summarizer prompt template. Intended to be injected into
pipeline tools that need LLM summarization without importing from
intellisource.llm directly.
"""

from __future__ import annotations

import json
from typing import Any

from intellisource.llm.prompts import load_prompt
from intellisource.observability.logging import get_logger

logger = get_logger(__name__)


async def llm_summarize(
    cluster_contents: list[dict[str, str]],
    gateway: Any,
) -> dict[str, Any] | None:
    """Call LLM gateway to produce a structured cluster summary.

    Args:
        cluster_contents: List of dicts with ``title`` and ``body_text``.
        gateway: LLM gateway instance with a ``complete`` method.

    Returns:
        Dict with title, summary, timeline, key_points; or None on failure.
    """
    docs_text = "\n\n".join(
        f"Title: {doc.get('title', '')}\n{doc.get('body_text', '')}"
        for doc in cluster_contents
    )
    try:
        prompt = load_prompt("summarizer", style="structured", docs_text=docs_text)
        llm_result = await gateway.complete(
            prompt=prompt,
            task_type="summarize",
            response_format={"type": "json_object"},
        )
        parsed = json.loads(llm_result.content)
    except Exception:
        logger.warning("LLM summarize failed in agent summarizer")
        return None

    required_keys = {"title", "summary", "timeline", "key_points"}
    if not required_keys.issubset(parsed.keys()):
        logger.warning("LLM response missing required keys in agent summarizer")
        return None

    return {
        "title": str(parsed["title"]),
        "summary": str(parsed["summary"]),
        "timeline": list(parsed["timeline"]),
        "key_points": list(parsed["key_points"]),
    }
