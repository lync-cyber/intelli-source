"""LLM prompt template loading.

Prompts ship as ``{name}.prompt.md`` (optionally ``{name}.{style}.prompt.md``
for a variant): YAML front-matter (``description`` / ``required_vars``)
followed by a Jinja body (``{{ var }}``). Front-matter is stripped before
rendering, declared ``required_vars`` are validated against the kwargs, and the
body may ``{% include %}`` / ``{% from ... import %}`` reusable partials from
``_fragments/`` (rendered through the same engine).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

import yaml
from jinja2 import BaseLoader, Environment, TemplateNotFound
from jinja2.sandbox import SandboxedEnvironment

from intellisource.core.encoding import read_text

_TEMPLATE_DIR = Path(__file__).parent


class _FragmentLoader(BaseLoader):
    """Resolve ``{% include %}`` targets against the current ``_TEMPLATE_DIR``.

    Reads the module-level ``_TEMPLATE_DIR`` at call time (not construction) so
    tests that monkeypatch it still resolve fragments from the right place.
    """

    def get_source(
        self, _environment: Environment, template: str
    ) -> tuple[str, str, Callable[[], bool]]:
        path = _TEMPLATE_DIR / template
        if not path.exists():
            raise TemplateNotFound(template)
        source = read_text(path)
        mtime = path.stat().st_mtime
        return source, str(path), lambda: path.stat().st_mtime == mtime


# autoescape is off: prompt bodies are plain text for an LLM, not HTML.
_jinja_env = SandboxedEnvironment(
    autoescape=False, trim_blocks=True, lstrip_blocks=True, loader=_FragmentLoader()
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
def _read_prompt_md(name: str, style: str | None = None) -> tuple[PromptMeta, str]:
    """Read+parse a ``.prompt.md`` template, preferring variant over base.

    Raises:
        FileNotFoundError: when neither the variant nor the base file exists.
    """
    _validate_path_component(name, "name")
    candidates: list[Path] = []
    if style is not None:
        _validate_path_component(style, "style")
        candidates.append(_TEMPLATE_DIR / f"{name}.{style}.prompt.md")
    candidates.append(_TEMPLATE_DIR / f"{name}.prompt.md")
    for path in candidates:
        if path.exists():
            return _parse_front_matter(read_text(path), name)
    raise FileNotFoundError(
        f"No prompt template for {name!r}"
        + (f" (style {style!r})" if style else "")
        + f": looked for {[p.name for p in candidates]} in {_TEMPLATE_DIR}"
    )


def read_prompt_source(name: str, style: str | None = None) -> str:
    """Return the raw (post-front-matter) Jinja body of a prompt template.

    Raises FileNotFoundError when the template is absent — callers use this to
    fail fast on an unknown prompt name.
    """
    _validate_path_component(name, "name")
    _, body = _read_prompt_md(name, style)
    return body


def load_prompt(name: str, *, style: str | None = None, **kwargs: Any) -> str:
    """Load a prompt template and render it with *kwargs*.

    Args:
        name: Template name (without extension).
        style: Optional variant style (e.g. ``"structured"``, ``"concise"``).
        **kwargs: Variables to substitute in the template.

    Returns:
        The rendered prompt string.

    Raises:
        FileNotFoundError: when no matching ``.prompt.md`` exists.
        ValueError: when declared ``required_vars`` are not all supplied.
    """
    _validate_path_component(name, "name")
    meta, body = _read_prompt_md(name, style)
    missing = [v for v in meta.required_vars if v not in kwargs]
    if missing:
        raise ValueError(f"Prompt {name!r} missing required vars: {missing}")
    return _jinja_env.from_string(body).render(**kwargs)
