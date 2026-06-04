"""TemplateConfig — value object + structural validation for digest templates.

A custom (DB-backed) digest template reuses a built-in ``base_template``'s
aggregation logic and supplies its own per-format Jinja source. Structural
validation (formats / default_format / jinja_source consistency) lives here;
the cross-cutting check that ``base_template`` names a real built-in lives in
``TemplateService`` so this config layer keeps no edge to the distributor.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator

_JSON_FORMAT = "json"
_ALLOWED_STATUS = frozenset({"active", "archived"})


class TemplateValidationError(ValueError):
    """Raised when a template definition is invalid."""


class TemplateConfig(BaseModel):
    """Configuration for a single custom digest template, mirrored from the ORM."""

    name: str
    base_template: str
    formats: list[str] = Field(default_factory=list)
    default_format: str = ""
    jinja_source: dict[str, str] = Field(default_factory=dict)
    aggregate_config: dict[str, Any] = Field(default_factory=dict)
    status: str = "active"

    @model_validator(mode="after")
    def _check_consistency(self) -> TemplateConfig:
        if not self.name:
            raise ValueError("name is required")
        if not self.base_template:
            raise ValueError("base_template is required")
        if not self.formats:
            raise ValueError("formats must be non-empty")
        if self.default_format not in self.formats:
            raise ValueError(
                f"default_format {self.default_format!r} not in formats {self.formats}"
            )
        extra = sorted(set(self.jinja_source) - set(self.formats))
        if extra:
            raise ValueError(f"jinja_source declares formats not in formats: {extra}")
        if self.status not in _ALLOWED_STATUS:
            allowed = sorted(_ALLOWED_STATUS)
            raise ValueError(f"invalid status {self.status!r}; allowed: {allowed}")
        return self
