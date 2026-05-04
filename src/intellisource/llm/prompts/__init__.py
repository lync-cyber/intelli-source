"""LLM prompt template loader.

Loads .txt prompt templates from this package directory and supports
variable substitution via str.format_map().
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

_TEMPLATE_DIR = Path(__file__).parent


@lru_cache(maxsize=64)
def _read_template(name: str, style: str | None = None) -> str:
    """Read and cache a template file, preferring variant over base.

    When style is provided, attempts to load ``{name}.{style}.txt``
    first; falls back to ``{name}.txt`` when the variant is absent.
    """
    if style is not None:
        variant_path = _TEMPLATE_DIR / f"{name}.{style}.txt"
        if variant_path.exists():
            return variant_path.read_text(encoding="utf-8")
    path = _TEMPLATE_DIR / f"{name}.txt"
    return path.read_text(encoding="utf-8")


def load_prompt(name: str, *, style: str | None = None, **kwargs: Any) -> str:
    """Load a prompt template and substitute variables.

    Args:
        name: Template name (without .txt extension).
        style: Optional variant style (e.g. ``"structured"``, ``"concise"``).
            When provided, tries ``{name}.{style}.txt`` first and falls back
            to ``{name}.txt`` when the variant is absent. Callers that omit
            this parameter see identical behaviour to the previous API.
        **kwargs: Variables to substitute in the template.

    Returns:
        The formatted prompt string.
    """
    template = _read_template(name, style)
    if kwargs:
        return template.format_map(kwargs)
    return template
