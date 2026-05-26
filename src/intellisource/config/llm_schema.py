"""LLM configuration Pydantic schema models.

These models define the structure and validation rules for llm_models.yaml.
They live in the config module (M-001) as per arch-modules §2.M-001.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

ThinkingMode = Literal["enabled", "disabled"]
ReasoningEffort = Literal["high", "max"]


class ModelTaskConfig(BaseModel):
    """Pydantic model for a single task-type model configuration."""

    model: str
    provider: str
    temperature: float | None = None
    max_tokens: int | None = None
    thinking: ThinkingMode | None = None
    reasoning_effort: ReasoningEffort | None = None

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
    thinking: ThinkingMode | None = None
    reasoning_effort: ReasoningEffort | None = None


class DefaultModelConfig(BaseModel):
    """Pydantic model for the default_model section."""

    model: str
    provider: str


class LLMModelsConfig(BaseModel):
    """Pydantic schema for the full llm_models.yaml configuration."""

    default_model: DefaultModelConfig
    models: dict[str, ModelTaskConfig] = Field(default_factory=dict)
    profiles: dict[str, ModelProfileConfig] = Field(default_factory=dict)
