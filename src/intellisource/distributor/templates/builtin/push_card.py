"""push-card — single-item instant notification (text / markdown / news)."""

from __future__ import annotations

from typing import Any

from intellisource.distributor.templates.base import DigestTemplate
from intellisource.distributor.templates.builtin._common import to_item
from intellisource.distributor.templates.schemas import DigestBundle, DigestSection


class PushCardTemplate(DigestTemplate):
    name = "push-card"
    formats = frozenset({"text", "markdown", "news"})
    default_format = "text"

    def aggregate(self, contents: list[Any], config: dict[str, Any]) -> DigestBundle:
        items = [to_item(content) for content in contents[:1]]
        title = items[0].title if items else ""
        return DigestBundle(
            title=title,
            sections=[DigestSection(heading="", items=items)] if items else [],
        )

    def render(self, bundle: DigestBundle, fmt: str | None = None) -> Any:
        chosen = (
            fmt if (fmt is not None and fmt in self.formats) else self.default_format
        )
        if chosen == "news":
            items = bundle.sections[0].items if bundle.sections else []
            return [
                {
                    "title": item.title,
                    "description": item.summary,
                    "url": item.source_url or "",
                }
                for item in items
            ]
        return super().render(bundle, chosen)
