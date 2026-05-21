"""ConfigValidator for parsing and validating source configuration files."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Final

import yaml
from pydantic import ValidationError

from intellisource.config.models import SourceConfig

_ENV_VAR_PATTERN: Final[re.Pattern[str]] = re.compile(r"\$\{([^}]+)\}")

_JsonValue = str | int | float | bool | None | dict[str, Any] | list[Any]


def _resolve_env_vars(value: _JsonValue) -> _JsonValue:
    """Recursively resolve ${ENV_VAR} placeholders in string values."""
    if isinstance(value, str):

        def _replace(match: re.Match[str]) -> str:
            var_name = match.group(1)
            env_value = os.environ.get(var_name)
            if env_value is None:
                raise ValueError(f"Undefined environment variable: {var_name}")
            return env_value

        return _ENV_VAR_PATTERN.sub(_replace, value)
    if isinstance(value, dict):
        return {k: _resolve_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_env_vars(item) for item in value]
    return value


class ConfigValidator:
    """Validates source configuration data."""

    def validate(self, config: SourceConfig) -> SourceConfig:
        """Validate a SourceConfig instance; returns it unchanged."""
        return config

    def validate_source(self, data: dict[str, Any]) -> SourceConfig:
        """Validate a single source configuration dict.

        Returns a SourceConfig on success, raises ValidationError on failure.
        """
        return SourceConfig.model_validate(data)

    def validate_sources_file(
        self,
        content: str,
        *,
        format: str,  # noqa: A002
    ) -> list[SourceConfig]:
        """Parse and validate a YAML or JSON configuration string.

        Args:
            content: The raw YAML or JSON string.
            format: Either 'yaml' or 'json'.

        Returns:
            A list of validated SourceConfig instances.

        Raises:
            ValueError: If there are validation errors across sources.
            yaml.YAMLError: If YAML syntax is invalid.
            json.JSONDecodeError: If JSON syntax is invalid.
        """
        if format == "yaml":
            parsed = yaml.safe_load(content)
        elif format == "json":
            parsed = json.loads(content)
        else:
            raise ValueError(f"Unsupported format: {format}")

        sources_raw: list[Any] = parsed.get("sources", [])

        # Resolve environment variables before validation
        sources_resolved = _resolve_env_vars(sources_raw)

        results: list[SourceConfig] = []
        errors: list[str] = []

        if not isinstance(sources_resolved, list):
            raise ValueError("Expected 'sources' to be a list")

        for i, source_data in enumerate(sources_resolved):
            try:
                results.append(self.validate_source(source_data))
            except ValidationError as e:
                errors.append(f"Source index {i}: {e}")

        if errors:
            raise ValueError(
                f"Validation failed for {len(errors)} source(s):\n" + "\n".join(errors)
            )

        return results
