"""Jinja2 render engine for digest templates.

A single sandboxed environment is shared by all templates. The loader resolves
``config/templates`` (user overrides) before the packaged ``builtin`` directory,
so a user-supplied ``{name}.{fmt}.j2`` of the same name takes precedence.

Autoescape is enabled only for ``*.html.j2`` so plain-text / markdown templates
are not HTML-escaped.
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import FileSystemLoader
from jinja2.sandbox import SandboxedEnvironment

from intellisource.distributor.templates.schemas import DigestBundle

_BUILTIN_DIR = Path(__file__).parent / "builtin"
_USER_DIR = Path("config") / "templates"


def _autoescape(template_name: str | None) -> bool:
    return template_name is not None and template_name.endswith(".html.j2")


_env = SandboxedEnvironment(
    loader=FileSystemLoader([str(_USER_DIR), str(_BUILTIN_DIR)]),
    autoescape=_autoescape,
    trim_blocks=True,
    lstrip_blocks=True,
)


def render_jinja(template_name: str, fmt: str, bundle: DigestBundle) -> str:
    """Render ``{template_name}.{fmt}.j2`` with the bundle exposed as ``bundle``."""
    template = _env.get_template(f"{template_name}.{fmt}.j2")
    return template.render(bundle=bundle)
