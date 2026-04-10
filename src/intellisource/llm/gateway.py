"""LLM unified gateway with schema enforcement.

Provides LLMGateway for calling LLMs via litellm, SchemaEnforcer for
validating outputs against JSON Schema, and SchemaValidationError.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from intellisource.llm.cache import LLMCache

import jsonschema
import litellm

from intellisource.core.errors import ErrorCategory, LLMError
from intellisource.llm.model_config import load_model_config
from intellisource.llm.prompt_builder import PromptBuilder

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG_PATH = str(
    Path(__file__).resolve().parents[3] / "config" / "llm_models.yaml"
)


def _load_routing_config() -> dict[str, Any]:
    """Load model routing config from env var or default path.

    Falls back to an empty config if the file does not exist.
    """
    config_path = os.environ.get("IS_LLM_CONFIG_PATH", _DEFAULT_CONFIG_PATH)
    path = Path(config_path)
    if not path.exists():
        logger.warning(
            "LLM routing config not found at '%s', using empty config",
            config_path,
        )
        return {"default_model": {"model": "gpt-4o-mini"}, "models": {}}
    return load_model_config(config_path)


class SchemaValidationError(LLMError):
    """Raised when LLM output fails JSON Schema validation."""

    def __init__(
        self,
        message: str,
        category: ErrorCategory = ErrorCategory.RECOVERABLE_DEGRADED,
        recovery_hint: str = "",
    ) -> None:
        super().__init__(message, category=category, recovery_hint=recovery_hint)


@dataclass
class LLMResult:
    """Result from an LLM completion call."""

    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


class SchemaEnforcer:
    """Validates LLM output against a JSON Schema."""

    def __init__(self, schema: dict[str, Any]) -> None:
        self._schema = schema

    def validate(self, raw_output: str) -> dict[str, Any]:
        """Parse and validate raw LLM output against the schema.

        Args:
            raw_output: Raw JSON string from LLM.

        Returns:
            Parsed and validated dictionary.

        Raises:
            SchemaValidationError: If parsing or validation fails.
        """
        try:
            data = json.loads(raw_output)
        except json.JSONDecodeError as exc:
            raise SchemaValidationError(f"Invalid JSON: {exc}") from exc

        try:
            jsonschema.validate(instance=data, schema=self._schema)
        except jsonschema.ValidationError as exc:
            raise SchemaValidationError(
                f"Schema validation failed: {exc.message}"
            ) from exc

        return dict(data)


class LLMGateway:
    """Unified LLM calling interface built on litellm."""

    _CONTEXT_WINDOWS: dict[str, int] = {
        "gpt-4o-mini": 128000,
        "gpt-4o": 128000,
        "claude-3-haiku-20240307": 200000,
        "claude-sonnet-4-20250514": 200000,
    }
    _DEFAULT_CONTEXT_WINDOW = 128000

    def __init__(self, cache: LLMCache | None = None) -> None:
        self._default_temperature: float = 0.7
        self._default_max_tokens: int = 4096
        self._routing_config: dict[str, Any] = _load_routing_config()
        self._cache: LLMCache | None = cache

    async def complete(
        self,
        prompt: str,
        model: str | None = None,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        task_type: str | None = None,
        cache_key_parts: dict[str, str] | None = None,
        max_input_tokens: int | None = None,
    ) -> LLMResult:
        """Call an LLM with standardized parameters.

        Args:
            prompt: The user prompt.
            model: Model identifier (overrides task_type routing).
            system_prompt: Optional system message.
            temperature: Sampling temperature.
            max_tokens: Maximum tokens to generate.
            task_type: Task type for automatic model routing.
            cache_key_parts: Optional dict with keys content_fingerprint,
                call_type, prompt_version for cache lookup/storage.
            max_input_tokens: Optional max input token limit. If set or if
                estimated tokens exceed 80% of model context window, the
                user prompt is truncated.

        Returns:
            LLMResult with content and metadata.
        """
        # Check cache before calling LLM
        if self._cache is not None and cache_key_parts is not None:
            cached = await self._cache.get(
                content_fingerprint=cache_key_parts["content_fingerprint"],
                call_type=cache_key_parts["call_type"],
                prompt_version=cache_key_parts["prompt_version"],
            )
            if cached is not None:
                return cached

        resolved_model = model

        if resolved_model is None and task_type is not None:
            models = self._routing_config.get("models", {})
            if task_type in models:
                resolved_model = models[task_type]["model"]
            else:
                logger.warning(
                    "No model config for task_type '%s', using default_model",
                    task_type,
                )
                resolved_model = self._routing_config["default_model"]["model"]

        if resolved_model is None:
            resolved_model = "gpt-4o-mini"

        # Token truncation: apply if max_input_tokens is set or if
        # estimated tokens exceed 80% of the model context window.
        estimated = self.estimate_tokens(prompt, resolved_model)
        context_window = self._CONTEXT_WINDOWS.get(
            resolved_model, self._DEFAULT_CONTEXT_WINDOW
        )
        threshold = int(context_window * 0.8)
        effective_limit: int | None = None

        if max_input_tokens is not None and estimated > max_input_tokens:
            effective_limit = max_input_tokens
        elif estimated > threshold:
            effective_limit = threshold

        if effective_limit is not None:
            logger.warning(
                "Prompt tokens (%d) exceed limit (%d) for model '%s', truncating",
                estimated,
                effective_limit,
                resolved_model,
            )
            prompt = PromptBuilder.truncate_content(
                prompt, effective_limit, resolved_model
            )

        messages: list[dict[str, str]] = []
        if system_prompt is not None:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        start_time = time.monotonic()
        response = await litellm.acompletion(
            model=resolved_model,
            messages=messages,
            temperature=temperature
            if temperature is not None
            else self._default_temperature,
            max_tokens=max_tokens
            if max_tokens is not None
            else self._default_max_tokens,
        )
        elapsed_ms = (time.monotonic() - start_time) * 1000

        content: str = response.choices[0].message.content
        metadata: dict[str, Any] = {
            "input_tokens": response.usage.prompt_tokens,
            "output_tokens": response.usage.completion_tokens,
            "latency_ms": elapsed_ms,
            "model": response.model,
        }

        result = LLMResult(content=content, metadata=metadata)

        # Cache the result after successful LLM call
        if self._cache is not None and cache_key_parts is not None:
            await self._cache.set(
                content_fingerprint=cache_key_parts["content_fingerprint"],
                call_type=cache_key_parts["call_type"],
                prompt_version=cache_key_parts["prompt_version"],
                result=result,
            )

        return result

    def estimate_tokens(self, text: str, model: str) -> int:
        """Estimate token count for text.

        Prefers litellm.token_counter; falls back to len(text)//4 heuristic.

        Args:
            text: Input text to count tokens for.
            model: Model identifier for tokenizer selection.

        Returns:
            Estimated token count.
        """
        try:
            count = litellm.token_counter(model=model, text=text)
            if isinstance(count, int):
                return count
            return len(text) // 4
        except Exception:
            return len(text) // 4
