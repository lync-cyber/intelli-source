"""FormatConverter processor: normalizes content formatting."""

import re

from intellisource.pipeline.base import BaseProcessor
from intellisource.pipeline.context import PipelineContext


class FormatConverter(BaseProcessor):
    """Normalize whitespace, line endings, and blank lines in body_text."""

    def process(self, context: PipelineContext) -> PipelineContext:
        body_text: str = context.get("body_text") or ""
        if not body_text:
            context.set("body_text", "")
            return context
        # Normalize line endings: \r\n -> \n, then \r -> \n
        text = body_text.replace("\r\n", "\n").replace("\r", "\n")
        # Collapse multiple spaces (not newlines) to single space per line
        lines = text.split("\n")
        lines = [re.sub(r" {2,}", " ", line) for line in lines]
        text = "\n".join(lines)
        # Collapse 3+ consecutive newlines to 2 (one blank line)
        text = re.sub(r"\n{3,}", "\n\n", text)
        # Strip leading/trailing whitespace
        text = text.strip()
        context.set("body_text", text)
        return context
