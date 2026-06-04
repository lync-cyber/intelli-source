"""DbDigestTemplate — a DigestTemplate whose render source lives in the database.

Reuses a named built-in template's aggregation logic (``base_template``) and
renders from a per-format Jinja source string stored alongside it, so a user can
define a new digest template at runtime without shipping a Python class or a
packaged ``.j2`` file. Rendering goes through the shared sandboxed Jinja
environment (:func:`render_jinja_source`).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from intellisource.distributor.templates.base import DigestTemplate
from intellisource.distributor.templates.registry import get_template, register_template
from intellisource.distributor.templates.render import render_jinja_source
from intellisource.distributor.templates.renderers import Renderer
from intellisource.distributor.templates.schemas import DigestBundle


class DbDigestTemplate(DigestTemplate):
    """A digest template backed by DB-stored Jinja source + a built-in base."""

    def __init__(
        self,
        *,
        name: str,
        formats: Iterable[str],
        default_format: str,
        base_template: str,
        jinja_source: dict[str, str],
        aggregate_config: dict[str, Any] | None = None,
    ) -> None:
        self.name = name
        self.formats = frozenset(formats)
        self.default_format = default_format
        self._base_template = base_template
        self._jinja_source = dict(jinja_source)
        self._aggregate_config = dict(aggregate_config or {})

    def aggregate(self, contents: list[Any], config: dict[str, Any]) -> DigestBundle:
        """Delegate aggregation to the named built-in base template.

        The per-call ``config`` overlays the template's stored ``aggregate_config``.
        """
        base = get_template(self._base_template)
        merged = {**self._aggregate_config, **(config or {})}
        return base.aggregate(contents, merged)

    async def render(
        self,
        bundle: DigestBundle,
        fmt: str | None = None,
        *,
        renderer: Renderer | None = None,
        config: dict[str, Any] | None = None,
    ) -> Any:
        """Render from the stored Jinja source for *fmt* (built-in base fallback)."""
        chosen = (
            fmt if (fmt is not None and fmt in self.formats) else self.default_format
        )
        if chosen == "json":
            return bundle.model_dump(mode="json")
        source = self._jinja_source.get(chosen)
        if source is None:
            # format is declared but has no stored source — fall back to the base
            # built-in's packaged template rather than failing the push.
            base = get_template(self._base_template)
            return await base.render(bundle, chosen, renderer=renderer, config=config)
        return render_jinja_source(source, chosen, bundle)


def db_template_from_row(row: Any) -> DbDigestTemplate:
    """Build a :class:`DbDigestTemplate` from a persisted ``Template`` row."""
    return DbDigestTemplate(
        name=row.name,
        formats=row.formats,
        default_format=row.default_format,
        base_template=row.base_template,
        jinja_source=row.jinja_source,
        aggregate_config=row.aggregate_config,
    )


def register_db_templates(rows: Iterable[Any]) -> int:
    """Register DB-backed templates into the shared registry (last write wins).

    Returns the number of templates registered. Called at process startup to
    make custom templates resolvable by the synchronous distribution render path
    (``get_template`` / ``resolve_template_for``) alongside the built-ins.
    """
    count = 0
    for row in rows:
        register_template(db_template_from_row(row))
        count += 1
    return count
