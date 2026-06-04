"""topic-deepdive — single-item deep read: TL;DR + key points + body + timeline."""

from __future__ import annotations

from typing import Any

from intellisource.distributor.templates.base import DigestTemplate
from intellisource.distributor.templates.builtin._common import timeline_from, to_item
from intellisource.distributor.templates.schemas import (
    DigestBundle,
    DigestSection,
)


class TopicDeepDiveTemplate(DigestTemplate):
    name = "topic-deepdive"
    formats = frozenset({"html", "markdown"})
    default_format = "html"

    def aggregate(self, contents: list[Any], config: dict[str, Any]) -> DigestBundle:
        if not contents:
            return DigestBundle(title="")
        item = to_item(contents[0])
        return DigestBundle(
            title=item.title,
            sections=[DigestSection(heading="", items=[item])],
            timeline=timeline_from(contents[0]),
        )
