"""LLM model routing configuration loading.

Provides task_type -> model mapping from YAML config files.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError as PydanticValidationError

from intellisource.config.llm_schema import (
    DefaultModelConfig,
    LLMModelsConfig,
    ModelProfileConfig,
    ModelTaskConfig,
)
from intellisource.core.encoding import read_text
from intellisource.observability.logging import get_logger

logger = get_logger(__name__)

__all__ = [
    "DefaultModelConfig",
    "LLMModelsConfig",
    "ModelProfile",
    "ModelProfileConfig",
    "ModelRoutingConfig",
    "ModelTaskConfig",
    "load_model_config",
]


@dataclass
class ModelProfile:
    """Per-model default parameters."""

    temperature: float
    max_tokens: int
    context_window: int
    prompt_style: str = "default"
    timeout_seconds: int = 60
    thinking: str | None = None
    reasoning_effort: str | None = None


class ModelRoutingConfig:
    """Task-type to model routing lookup."""

    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config

    def get_model(self, task_type: str) -> dict[str, Any]:
        """Return model config for a task_type, falling back to default."""
        models: dict[str, Any] = self._config.get("models", {})
        if task_type in models:
            return dict(models[task_type])
        logger.warning(
            "No model config for task_type '%s', using default_model", task_type
        )
        return dict(self._config["default_model"])

    @property
    def available_task_types(self) -> list[str]:
        """Return list of configured task types."""
        return list(self._config.get("models", {}).keys())

    def get_fallback_models(self, task_type: str) -> list[str]:
        """Return the ordered fallback model ids for a task_type (may be empty).

        Tried in order after the primary model's own retries are exhausted, so a
        provider/model outage degrades to the next configured model before the
        non-LLM degradation fallback runs.
        """
        cfg = self._config.get("models", {}).get(task_type)
        if not isinstance(cfg, dict):
            return []
        fallbacks = cfg.get("fallback_models", [])
        if not isinstance(fallbacks, list):
            return []
        return [str(m) for m in fallbacks]

    def get_profile(self, model: str) -> ModelProfile | None:
        """Return ModelProfile for a model ID, or None if not configured."""
        profiles: dict[str, Any] = self._config.get("profiles", {})
        if model not in profiles:
            return None
        p = profiles[model]
        return ModelProfile(
            temperature=p["temperature"],
            max_tokens=p["max_tokens"],
            context_window=p["context_window"],
            prompt_style=p.get("prompt_style", "default"),
            timeout_seconds=p.get("timeout_seconds", 60),
            thinking=p.get("thinking"),
            reasoning_effort=p.get("reasoning_effort"),
        )

    @property
    def default_model(self) -> dict[str, Any]:
        """Return the default model config."""
        return dict(self._config["default_model"])


def load_model_config(path: str) -> dict[str, Any]:
    """Load model routing config from a YAML file.

    Args:
        path: Path to the YAML config file.

    Returns:
        Parsed config dictionary with 'default_model' and 'models' keys.

    Raises:
        FileNotFoundError: If the config file does not exist.
        ValueError: If the file is empty, missing required keys, or YAML is malformed.
        pydantic.ValidationError: If the config fails LLMModelsConfig schema validation.
    """
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    text = read_text(file_path)
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"Malformed YAML config file {path}: {exc}") from exc

    if data is None:
        raise ValueError(f"Config file is empty: {path}")

    if not isinstance(data, dict):
        raise ValueError(f"Config file must contain a YAML mapping: {path}")

    if "default_model" not in data:
        raise ValueError(f"Config file missing required key 'default_model': {path}")

    # Validate schema via Pydantic (raises ValidationError on invalid data).
    LLMModelsConfig.model_validate(data)

    return dict(data)


# Keep PydanticValidationError accessible for callers that need to handle it.
__all__ += ["PydanticValidationError"]
