"""LLM model routing configuration loading.

Provides task_type -> model mapping from YAML config files.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


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

    return dict(data)
