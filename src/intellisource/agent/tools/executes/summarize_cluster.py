"""Cluster summarization — LLM digest with truncation fallback.

Lives in the agent layer because the LLM path needs ``load_prompt`` from
``intellisource.llm``, which importlinter Contract 2 forbids the pipeline layer
from importing. The pure truncation fallback stays in
``pipeline.processors.tools`` and is reused here via ``truncate_fallback``.

Two wrappers share one core (``_summarize_core``):
- ``_summarize_cluster_execute`` — the agent-callable tool execute (reads the
  gateway from ``tool_deps``).
- ``make_cluster_summarizer`` — binds a gateway into a plain callable that
  ``agent.factory`` injects into the pipeline ``LLMSummarizer`` processor (which
  cannot import this module: pipeline ✗→ agent).
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from intellisource.agent.deps import ToolDeps
from intellisource.llm.prompts import load_prompt
from intellisource.observability.logging import get_logger
from intellisource.pipeline.digest.schemas import ContentDigest, parse_digest
from intellisource.pipeline.processors.tools import truncate_fallback

logger = get_logger(__name__)

ClusterSummarizer = Callable[[list[dict[str, str]]], Awaitable[dict[str, Any]]]


async def _llm_summarize(
    cluster_contents: list[dict[str, str]], gateway: Any
) -> ContentDigest | None:
    """Call the LLM for a structured cluster digest; return None on failure."""
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
        logger.warning("LLM summarize failed, falling back to truncation")
        return None

    digest = parse_digest(parsed)
    if digest is None:
        logger.warning("LLM response missing required keys, falling back")
    return digest


async def _summarize_core(
    cluster_contents: list[dict[str, str]], gateway: Any
) -> dict[str, Any]:
    """LLM digest when a gateway is available, else truncation fallback."""
    if not cluster_contents:
        return ContentDigest(title="", summary="").model_dump()
    if gateway is not None:
        digest = await _llm_summarize(cluster_contents, gateway)
        if digest is not None:
            return digest.model_dump()
    return truncate_fallback(cluster_contents).model_dump()


async def _summarize_cluster_execute(
    cluster_contents: list[dict[str, str]],
    *,
    tool_deps: ToolDeps | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Agent tool: structured digest (title/summary/timeline/key_points)."""
    gateway = tool_deps.llm_gateway if tool_deps is not None else None
    return await _summarize_core(cluster_contents, gateway)


def make_cluster_summarizer(gateway: Any) -> ClusterSummarizer:
    """Bind *gateway* into a summarizer callable for processor injection."""

    async def _summarize(cluster_contents: list[dict[str, str]]) -> dict[str, Any]:
        return await _summarize_core(cluster_contents, gateway)

    return _summarize
