"""HTMLParser processor: extracts plain text from HTML content."""

import html
import re

from intellisource.core.processor import BaseProcessor, PipelineContext


class HTMLParser(BaseProcessor):
    """Strip HTML tags and decode entities, storing result in body_text."""

    def process(self, context: PipelineContext) -> PipelineContext:
        body_html: str = context.get("body_html") or ""
        # Remove HTML tags
        text = re.sub(r"<[^>]+>", "", body_html)
        # Decode HTML entities
        text = html.unescape(text)
        context.set("body_text", text)
        return context
