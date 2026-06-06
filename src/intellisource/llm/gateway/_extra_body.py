"""DeepSeek V4 extra_body builder.

Translates `thinking` / `reasoning_effort` from llm_models.yaml into the
extra_body payload that litellm forwards verbatim to the DeepSeek
chat/completions endpoint. Non-deepseek models receive no extra_body.

DeepSeek V4 contract (https://api-docs.deepseek.com/zh-cn/api/create-chat-completion):
- `thinking.type`: "enabled" (default) | "disabled"
- `reasoning_effort`: "high" (default) | "max"

Resolution precedence (first non-None wins):
  task_cfg → profile → provider default

Provider default for deepseek is `thinking="disabled"` — the chat-tool-loop
flow used by FlexibleLoop is fragile under thinking mode because the prior
turn's `message.reasoning_content` must be passed back verbatim to avoid
`The reasoning_content in the thinking mode must be passed back to the API.`
"""

from __future__ import annotations

from typing import Any


def _is_deepseek_model(model: str | None) -> bool:
    if not model:
        return False
    return model.startswith("deepseek/")


def build_extra_body(
    model: str | None,
    task_cfg: dict[str, Any] | None = None,
    profile: Any = None,
) -> dict[str, Any] | None:
    """Return an ``extra_body`` payload (or None when nothing to inject).

    *profile* may be a ``ModelProfile`` dataclass or ``None``. ``task_cfg``
    may be a raw dict from ``routing_config["models"][task_type]`` or ``None``.
    """
    if not _is_deepseek_model(model):
        return None

    thinking = (task_cfg or {}).get("thinking")
    if thinking is None and profile is not None:
        thinking = getattr(profile, "thinking", None)
    if thinking is None:
        thinking = "disabled"

    effort = (task_cfg or {}).get("reasoning_effort")
    if effort is None and profile is not None:
        effort = getattr(profile, "reasoning_effort", None)

    payload: dict[str, Any] = {"thinking": {"type": thinking}}
    if effort is not None:
        payload["reasoning_effort"] = effort
    return payload


def apply_extra_body(
    call_kwargs: dict[str, Any],
    routing_config: dict[str, Any],
    model: str,
    task_type: str | None,
    profile: Any,
) -> None:
    """Attach the provider ``extra_body`` payload to *call_kwargs* in place.

    Resolves the task-level config from *routing_config* for *task_type* and
    sets ``call_kwargs["extra_body"]`` only when a payload is produced.
    """
    task_cfg = (
        routing_config.get("models", {}).get(task_type)
        if task_type is not None
        else None
    )
    extra_body = build_extra_body(model, task_cfg, profile)
    if extra_body is not None:
        call_kwargs["extra_body"] = extra_body


def extract_reasoning_content(message: Any) -> str | None:
    """Read ``reasoning_content`` from a litellm response message, if present."""
    if message is None:
        return None
    value = getattr(message, "reasoning_content", None)
    if value is None and isinstance(message, dict):
        value = message.get("reasoning_content")
    if isinstance(value, str) and value:
        return value
    return None
