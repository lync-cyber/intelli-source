"""LLM prompt template loading.

Two template formats are supported in this package directory:

- ``{name}.prompt.md`` — YAML front-matter (``description`` / ``required_vars``)
  followed by a Jinja body (``{{ var }}``). Front-matter is stripped before
  rendering and declared ``required_vars`` are validated against the kwargs.
- ``{name}.txt`` — plain template substituted via ``str.format_map``.

When both exist for a name, ``.prompt.md`` takes precedence.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from jinja2.sandbox import SandboxedEnvironment

from intellisource.core.encoding import read_text

_TEMPLATE_DIR = Path(__file__).parent

# autoescape is off: prompt bodies are plain text for an LLM, not HTML.
_jinja_env = SandboxedEnvironment(
    autoescape=False, trim_blocks=True, lstrip_blocks=True
)


@dataclass(frozen=True)
class PromptMeta:
    """Front-matter declaration for a ``.prompt.md`` template."""

    name: str
    description: str = ""
    required_vars: tuple[str, ...] = ()


def _validate_path_component(value: str, field: str) -> None:
    if not value or "/" in value or "\\" in value or ".." in value or "\0" in value:
        raise ValueError(
            f"Invalid {field} for prompt template: {value!r} (must be a single "
            f"filename component without path separators or '..')"
        )


def _parse_front_matter(text: str, name: str) -> tuple[PromptMeta, str]:
    """Split optional ``---`` YAML front-matter from the template body."""
    meta_dict: dict[str, Any] = {}
    body = text
    if text.lstrip().startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            loaded = yaml.safe_load(parts[1]) or {}
            if isinstance(loaded, dict):
                meta_dict = loaded
            body = parts[2].lstrip("\n")
    required = meta_dict.get("required_vars") or []
    meta = PromptMeta(
        name=str(meta_dict.get("name", name)),
        description=str(meta_dict.get("description", "")),
        required_vars=tuple(str(v) for v in required),
    )
    return meta, body


@lru_cache(maxsize=64)
def _read_prompt_md(
    name: str, style: str | None = None
) -> tuple[PromptMeta, str] | None:
    """Read+parse a ``.prompt.md`` template, or return None when absent."""
    _validate_path_component(name, "name")
    candidates: list[Path] = []
    if style is not None:
        _validate_path_component(style, "style")
        candidates.append(_TEMPLATE_DIR / f"{name}.{style}.prompt.md")
    candidates.append(_TEMPLATE_DIR / f"{name}.prompt.md")
    for path in candidates:
        if path.exists():
            return _parse_front_matter(read_text(path), name)
    return None


@lru_cache(maxsize=64)
def _read_template(name: str, style: str | None = None) -> str:
    """Read and cache a ``.txt`` template, preferring variant over base.

    When style is provided, attempts to load ``{name}.{style}.txt``
    first; falls back to ``{name}.txt`` when the variant is absent.
    """
    _validate_path_component(name, "name")
    if style is not None:
        _validate_path_component(style, "style")
        variant_path = _TEMPLATE_DIR / f"{name}.{style}.txt"
        if variant_path.exists():
            return read_text(variant_path)
    path = _TEMPLATE_DIR / f"{name}.txt"
    return read_text(path)


def load_prompt(name: str, *, style: str | None = None, **kwargs: Any) -> str:
    """Load a prompt template and substitute variables.

    Args:
        name: Template name (without extension).
        style: Optional variant style (e.g. ``"structured"``, ``"concise"``).
        **kwargs: Variables to substitute in the template.

    Returns:
        The formatted prompt string.

    Raises:
        ValueError: when a ``.prompt.md`` declares ``required_vars`` not all
            supplied in *kwargs*.
    """
    _validate_path_component(name, "name")
    md = _read_prompt_md(name, style)
    if md is not None:
        meta, body = md
        missing = [v for v in meta.required_vars if v not in kwargs]
        if missing:
            raise ValueError(f"Prompt {name!r} missing required vars: {missing}")
        return _jinja_env.from_string(body).render(**kwargs)

    template = _read_template(name, style)
    if kwargs:
        return template.format_map(kwargs)
    return template
