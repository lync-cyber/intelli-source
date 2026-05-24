"""Shared types, dataclasses, and error classes for the LLM gateway."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import jsonschema

from intellisource.core.errors import ErrorCategory, LLMError


class SchemaValidationError(LLMError):
    """Raised when LLM output fails JSON Schema validation."""

    def __init__(
        self,
        message: str,
        category: ErrorCategory = ErrorCategory.RECOVERABLE_DEGRADED,
        recovery_hint: str = "",
    ) -> None:
        super().__init__(message, category=category, recovery_hint=recovery_hint)


class LLMOutputError(LLMError):
    """Raised when LLM output cannot be parsed or validated after enforcement."""

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
