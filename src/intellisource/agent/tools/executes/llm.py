"""LLM complete tool execute function."""

from __future__ import annotations

from typing import Any

from intellisource.agent.deps import ToolDeps
from intellisource.agent.tools.results import tool_degraded
from intellisource.observability.logging import get_logger

logger = get_logger(__name__)


async def _llm_complete_execute(
    call_type: str = "",
    prompt_vars: dict[str, Any] | None = None,
    tool_deps: ToolDeps | None = None,
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
        return tool_degraded(
            "llm_complete", "tool_deps not injected", call_type=call_type
        )
    result = await gateway.complete(prompt=prompt, task_type=call_type or None)
    return {
        "content": result.content,
        "call_type": call_type,
        "metadata": result.metadata,
    }
