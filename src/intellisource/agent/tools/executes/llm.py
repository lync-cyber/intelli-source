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
    gateway = tool_deps.llm_gateway if tool_deps is not None else None
    if gateway is None:
        logger.warning("tool_deps not injected for llm_complete, returning placeholder")
        return {
            "status": "degraded",
            "tool": "llm_complete",
            "reason": "tool_deps not injected",
            "call_type": call_type,
        }

    prompt_builder = None
    if call_type:
        try:
            from intellisource.llm.prompt_builder import PromptBuilder  # noqa: PLC0415

            prompt_builder = PromptBuilder(call_type=call_type, prompt_style="default")
            for key, value in prompt_vars.items():
                prompt_builder.add_context(key, str(value))
            prompt = prompt_builder.build()
        except FileNotFoundError:
            prompt_builder = None
            prompt = (
                " ".join(f"{k}: {v}" for k, v in prompt_vars.items())
                if prompt_vars
                else call_type
            )
    else:
        prompt = (
            " ".join(f"{k}: {v}" for k, v in prompt_vars.items())
            if prompt_vars
            else call_type
        )

    result = await gateway.complete(
        prompt=prompt,
        task_type=call_type or None,
        prompt_builder=prompt_builder,
    )
    return {
        "content": result.content,
        "call_type": call_type,
        "metadata": result.metadata,
    }
