"""DigestTemplate ABC — aggregation + render contract for output templates."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from intellisource.distributor.templates.renderers import JinjaRenderer, Renderer
from intellisource.distributor.templates.schemas import DigestBundle

_DEFAULT_RENDERER: Renderer = JinjaRenderer()


class DigestTemplate(ABC):
    """A named output template: aggregates content into a bundle, then renders it.

    Subclasses declare ``name``, the ``formats`` they support, and a
    ``default_format`` used when the requested format is unsupported.
    """

    name: str
    formats: frozenset[str]
    default_format: str

    @abstractmethod
    def aggregate(self, contents: list[Any], config: dict[str, Any]) -> DigestBundle:
        """Build a :class:`DigestBundle` from content rows (getattr-accessed)."""

    async def render(
        self,
        bundle: DigestBundle,
        fmt: str | None = None,
        *,
        renderer: Renderer | None = None,
        config: dict[str, Any] | None = None,
    ) -> Any:
        """Render *bundle* in *fmt* (falling back to ``default_format``).

        ``json`` returns the bundle as a plain dict; other formats are delegated
        to *renderer* (defaulting to the Jinja code renderer).
        """
        chosen = (
            fmt if (fmt is not None and fmt in self.formats) else self.default_format
        )
        if chosen == "json":
            return bundle.model_dump(mode="json")
        active = renderer or _DEFAULT_RENDERER
        return await active.render(
            template_name=self.name,
            fmt=chosen,
            bundle=bundle,
            config=config or {},
        )


__all__ = ["DigestTemplate"]
