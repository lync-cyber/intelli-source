"""SourceConfig Pydantic model for source configuration validation."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class SourceConfig(BaseModel):
    """Configuration for a single data source."""

    name: str
    type: Literal["rss", "api", "web"]
    url: str
    tags: list[str] = Field(default_factory=list)
    discipline_tags: list[str] = Field(default_factory=list)
    schedule_interval: int = 3600
    schedule_adaptive: bool = True
    proxy: str | None = None
    rate_limit_qps: float | None = None
    rate_limit_concurrency: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("url")
    @classmethod
    def url_must_be_valid(cls, v: str) -> str:
        """Validate that url looks like a proper URL."""
        if not v or "://" not in v:
            raise ValueError("Invalid URL: must contain a scheme (e.g. https://)")
        return v
