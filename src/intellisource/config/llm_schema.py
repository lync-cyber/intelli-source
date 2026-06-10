"""LLM configuration Pydantic schema models.

These models define the structure and validation rules for llm_models.yaml.
They live in the config module (M-001) as per arch-modules §2.M-001.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

ThinkingMode = Literal["enabled", "disabled"]
ReasoningEffort = Literal["high", "max"]

# Shared constrained aliases so the task layer and the profile layer validate
# identically. profiles is authoritative for temperature/max_tokens, so it must
# carry the same bounds as the task layer rather than accepting any number.
Temperature = Annotated[float, Field(ge=0.0, le=2.0)]
PositiveInt = Annotated[int, Field(gt=0)]


class ModelTaskConfig(BaseModel):
    """Pydantic model for a single task-type model configuration."""

    model_config = ConfigDict(extra="forbid")

    model: str
    provider: str
    temperature: Temperature | None = None
    max_tokens: PositiveInt | None = None
    thinking: ThinkingMode | None = None
    reasoning_effort: ReasoningEffort | None = None
    fallback_models: list[str] = Field(default_factory=list)


class ModelProfileConfig(BaseModel):
    """Pydantic model for a per-model profile configuration."""

    model_config = ConfigDict(extra="forbid")

    temperature: Temperature
    max_tokens: PositiveInt
    context_window: PositiveInt
    prompt_style: str = "default"
    timeout_seconds: PositiveInt = 60
    thinking: ThinkingMode | None = None
    reasoning_effort: ReasoningEffort | None = None


class DefaultModelConfig(BaseModel):
    """Pydantic model for the default_model section."""

    model_config = ConfigDict(extra="forbid")

    model: str
    provider: str


class LLMModelsConfig(BaseModel):
    """Pydantic schema for the full llm_models.yaml configuration."""

    model_config = ConfigDict(extra="forbid")

    default_model: DefaultModelConfig
    models: dict[str, ModelTaskConfig] = Field(default_factory=dict)
    profiles: dict[str, ModelProfileConfig] = Field(default_factory=dict)
