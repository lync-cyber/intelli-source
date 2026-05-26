"""LLM complete tool execute function."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def _llm_complete_execute(
    call_type: str = "",
    prompt_vars: dict[str, Any] | None = None,
    tool_deps: Any = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Invoke LLMGateway for a specific call_type with prompt_vars."""
    if prompt_vars is None:
        prompt_vars = {}
    prompt = (
        " ".join(f"{k}: {v}" for k, v in prompt_vars.items())
        if prompt_vars
        else call_type
    )
    gateway = tool_deps.llm_gateway if tool_deps is not None else None
    if gateway is None:
        logger.warning("tool_deps not injected for llm_complete, returning placeholder")
        return {
            "status": "degraded",
            "tool": "llm_complete",
            "reason": "tool_deps not injected",
            "call_type": call_type,
        }
    result = await gateway.complete(prompt=prompt, task_type=call_type or None)
    return {
        "content": result.content,
        "call_type": call_type,
        "metadata": result.metadata,
    }
