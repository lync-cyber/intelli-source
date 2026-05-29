"""ConfigValidator for parsing and validating source configuration files."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Final, get_args

import yaml
from pydantic import ValidationError

from intellisource.config.constants import MAX_NAME_LENGTH
from intellisource.config.models import SourceConfig

_ENV_VAR_PATTERN: Final[re.Pattern[str]] = re.compile(r"\$\{([^}]+)\}")

_JsonValue = str | int | float | bool | None | dict[str, Any] | list[Any]

_ALLOWED_SOURCE_TYPES: Final[frozenset[str]] = frozenset(
    get_args(SourceConfig.model_fields["type"].annotation)
)
_ALLOWED_URL_SCHEMES: Final[frozenset[str]] = frozenset({"http://", "https://"})
_PATH_TRAVERSAL_CHARS: Final[frozenset[str]] = frozenset({"..", "/", "\\"})


class ConfigValidationError(ValueError):
    """Raised when a SourceConfig fails semantic validation."""


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
        """Validate a SourceConfig instance with semantic security checks.

        Raises:
            ConfigValidationError: If any validation rule is violated.
        """
        name = config.name
        if not name:
            raise ConfigValidationError("name must be non-empty")
        if len(name) > MAX_NAME_LENGTH:
            raise ConfigValidationError(
                f"name length {len(name)} exceeds maximum {MAX_NAME_LENGTH}"
            )
        for forbidden in _PATH_TRAVERSAL_CHARS:
            if forbidden in name:
                raise ConfigValidationError(
                    f"name contains forbidden character: {forbidden!r}"
                )

        source_type = config.type
        if source_type not in _ALLOWED_SOURCE_TYPES:
            raise ConfigValidationError(
                f"type {source_type!r} is not one of {sorted(_ALLOWED_SOURCE_TYPES)}"
            )

        url = config.url
        if not any(url.startswith(scheme) for scheme in _ALLOWED_URL_SCHEMES):
            raise ConfigValidationError(
                f"url must start with http:// or https://, got: {url!r}"
            )

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
