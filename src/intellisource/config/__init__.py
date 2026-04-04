"""Configuration module for IntelliSource source definitions."""

from intellisource.config.models import SourceConfig
from intellisource.config.validator import ConfigValidator

__all__: list[str] = ["ConfigValidator", "SourceConfig"]
