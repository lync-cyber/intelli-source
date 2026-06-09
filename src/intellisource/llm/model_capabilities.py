"""Register first-party model capabilities with litellm.

litellm's shipped model map lags new releases, so ``supports_function_calling``
returns False for the deepseek v4 family and tool-using agents would silently
lose their tools. Registering the capabilities makes litellm aware of them.
"""

from __future__ import annotations

import litellm

_FUNCTION_CALLING_MODELS: tuple[str, ...] = (
    "deepseek/deepseek-v4-flash",
    "deepseek/deepseek-v4-pro",
)


def register_known_model_capabilities() -> None:
    """Mark known function-calling-capable models so litellm forwards tools."""
    for model in _FUNCTION_CALLING_MODELS:
        litellm.register_model(
            {
                model: {
                    "litellm_provider": "deepseek",
                    "mode": "chat",
                    "supports_function_calling": True,
                }
            }
        )
