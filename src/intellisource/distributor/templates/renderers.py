"""Renderer abstraction for digest bodies.

A :class:`Renderer` turns a :class:`DigestBundle` into a format string. The
default :class:`JinjaRenderer` wraps the packaged Jinja templates (the ``code``
render mode); the LLM-backed renderer lives in
``intellisource.distributor.llm_renderer`` and falls back to JinjaRenderer.
"""

from __future__ import annotations

from typing import Any, Protocol

from intellisource.distributor.templates.render import render_jinja
from intellisource.distributor.templates.schemas import DigestBundle


class Renderer(Protocol):
    """Render a bundle into a single format string."""

    async def render(
        self,
        *,
        template_name: str,
        fmt: str,
        bundle: DigestBundle,
        config: dict[str, Any],
    ) -> str: ...


class JinjaRenderer:
    """The ``code`` render mode: render the packaged ``{name}.{fmt}.j2`` template."""

    async def render(
        self,
        *,
        template_name: str,
        fmt: str,
        bundle: DigestBundle,
        config: dict[str, Any],
    ) -> str:
        return render_jinja(template_name, fmt, bundle)


__all__ = ["JinjaRenderer", "Renderer"]
