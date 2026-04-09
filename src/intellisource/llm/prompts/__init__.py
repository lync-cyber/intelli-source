"""LLM prompt template loader.

Loads .txt prompt templates from this package directory and supports
variable substitution via str.format_map().
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

_TEMPLATE_DIR = Path(__file__).parent


@lru_cache(maxsize=32)
def _read_template(name: str) -> str:
    """Read and cache a template file by name (without extension)."""
    path = _TEMPLATE_DIR / f"{name}.txt"
    return path.read_text(encoding="utf-8")


def load_prompt(name: str, **kwargs: Any) -> str:
    """Load a prompt template and substitute variables.

    Args:
        name: Template name (without .txt extension).
        **kwargs: Variables to substitute in the template.

    Returns:
        The formatted prompt string.
    """
    template = _read_template(name)
    if kwargs:
        return template.format_map(kwargs)
    return template
