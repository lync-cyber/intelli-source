"""LLM model routing configuration loading.

Provides task_type -> model mapping from YAML config files.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic schema models (T-061)
# ---------------------------------------------------------------------------


class ModelTaskConfig(BaseModel):
    """Pydantic model for a single task-type model configuration."""

    model: str
    provider: str
    temperature: float | None = None
    max_tokens: int | None = None

    @field_validator("temperature")
    @classmethod
    def temperature_in_range(cls, v: float | None) -> float | None:
        if v is not None and not (0.0 <= v <= 2.0):
            raise ValueError("temperature 必须在 0.0~2.0 之间")
        return v

    @field_validator("max_tokens")
    @classmethod
    def max_tokens_positive(cls, v: int | None) -> int | None:
        if v is not None and v <= 0:
            raise ValueError("max_tokens 必须大于 0")
        return v


class ModelProfileConfig(BaseModel):
    """Pydantic model for a per-model profile configuration."""

    temperature: float
    max_tokens: int
    context_window: int
    prompt_style: str = "default"
    timeout_seconds: int = 60


class DefaultModelConfig(BaseModel):
    """Pydantic model for the default_model section."""

    model: str
    provider: str


class LLMModelsConfig(BaseModel):
    """Pydantic schema for the full llm_models.yaml configuration."""

    default_model: DefaultModelConfig
    models: dict[str, ModelTaskConfig] = Field(default_factory=dict)
    profiles: dict[str, ModelProfileConfig] = Field(default_factory=dict)


@dataclass
class ModelProfile:
    """Per-model default parameters."""

    temperature: float
    max_tokens: int
    context_window: int
    prompt_style: str = "default"
    timeout_seconds: int = 60


@dataclass
class ModelConfig:
    """Individual model configuration."""

    model: str
    provider: str
    temperature: float | None = None
    max_tokens: int | None = None


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
        ValueError: If the file is empty or missing required keys.
        yaml.YAMLError: If the YAML is malformed.
    """
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    text = file_path.read_text()
    data = yaml.safe_load(text)

    if data is None:
        raise ValueError(f"Config file is empty: {path}")

    if not isinstance(data, dict):
        raise ValueError(f"Config file must contain a YAML mapping: {path}")

    if "default_model" not in data:
        raise ValueError(f"Config file missing required key 'default_model': {path}")

    # Validate schema via Pydantic (raises ValidationError on invalid data).
    LLMModelsConfig.model_validate(data)

    return dict(data)
