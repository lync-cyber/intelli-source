"""json-feed — structured JSON output for machine/webhook consumption."""

from __future__ import annotations

from typing import Any

from intellisource.distributor.templates.base import DigestTemplate
from intellisource.distributor.templates.builtin._common import to_item
from intellisource.distributor.templates.schemas import DigestBundle, DigestSection


class JsonFeedTemplate(DigestTemplate):
    name = "json-feed"
    formats = frozenset({"json"})
    default_format = "json"

    def aggregate(self, contents: list[Any], config: dict[str, Any]) -> DigestBundle:
        items = [to_item(content) for content in contents]
        return DigestBundle(
            title=str(config.get("title", "feed")),
            sections=[DigestSection(heading="all", items=items)] if items else [],
        )
