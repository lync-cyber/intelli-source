"""KeywordTagger processor: adds tags based on a predefined keyword library."""

from intellisource.core.processor import BaseProcessor, PipelineContext


class KeywordTagger(BaseProcessor):
    """Match keywords (case-insensitive) in body_text and assign tags."""

    def __init__(self, keywords: dict[str, list[str]] | None = None) -> None:
        self._keywords = keywords if keywords is not None else {}

    def process(self, context: PipelineContext) -> PipelineContext:
        body_text: str = context.get("body_text") or ""
        text_lower = body_text.lower()
        tags: list[str] = []
        for tag, synonyms in self._keywords.items():
            for synonym in synonyms:
                if synonym.lower() in text_lower:
                    if tag not in tags:
                        tags.append(tag)
                    break
        context.set("tags", tags)
        return context
