"""Tests for pipeline processors (AC-015, AC-T018-1..4).

Covers:
- AC-015: Each processor implements BaseProcessor and can be independently registered.
- AC-T018-1: HTMLParser extracts plain text from body_html into body_text.
- AC-T018-2: ContentDedup detects duplicate content via SHA-256 fingerprint.
- AC-T018-3: KeywordTagger adds tags based on a predefined keyword library.
- AC-T018-4: FormatConverter normalizes content (whitespace, encoding, line endings).
"""

import hashlib

from intellisource.pipeline.base import BaseProcessor
from intellisource.pipeline.context import PipelineContext
from intellisource.pipeline.processors.dedup import ContentDedup
from intellisource.pipeline.processors.formatter import FormatConverter
from intellisource.pipeline.processors.parser import HTMLParser
from intellisource.pipeline.processors.tagger import KeywordTagger


# ---------------------------------------------------------------------------
# AC-015: All processors implement BaseProcessor and can be independently registered
# ---------------------------------------------------------------------------
class TestProcessorBaseInterface:
    """AC-015: Every processor implements BaseProcessor and is pipeline-registrable."""

    def test_html_parser_is_base_processor(self):
        """HTMLParser should be a subclass of BaseProcessor."""
        processor = HTMLParser()
        assert isinstance(processor, BaseProcessor)

    def test_content_dedup_is_base_processor(self):
        """ContentDedup should be a subclass of BaseProcessor."""
        processor = ContentDedup()
        assert isinstance(processor, BaseProcessor)

    def test_keyword_tagger_is_base_processor(self):
        """KeywordTagger should be a subclass of BaseProcessor."""
        processor = KeywordTagger(keywords={})
        assert isinstance(processor, BaseProcessor)

    def test_format_converter_is_base_processor(self):
        """FormatConverter should be a subclass of BaseProcessor."""
        processor = FormatConverter()
        assert isinstance(processor, BaseProcessor)

    def test_processor_process_returns_pipeline_context(self):
        """process() should accept a PipelineContext and return a PipelineContext."""
        processor = HTMLParser()
        ctx = PipelineContext()
        ctx.set("body_html", "<p>hello</p>")
        result = processor.process(ctx)
        assert isinstance(result, PipelineContext)


# ---------------------------------------------------------------------------
# AC-T018-1: HTMLParser
# ---------------------------------------------------------------------------
class TestHTMLParser:
    """AC-T018-1: HTMLParser extracts plain text from body_html into body_text."""

    def test_strips_simple_html_tags(self):
        """HTML tags should be removed, leaving only text content."""
        processor = HTMLParser()
        ctx = PipelineContext()
        ctx.set("body_html", "<p>Hello <b>world</b></p>")
        result = processor.process(ctx)
        assert result.get("body_text") == "Hello world"

    def test_decodes_html_entities(self):
        """HTML entities like &amp; should be decoded to their characters."""
        processor = HTMLParser()
        ctx = PipelineContext()
        ctx.set("body_html", "<p>Tom &amp; Jerry &lt;3</p>")
        result = processor.process(ctx)
        assert result.get("body_text") == "Tom & Jerry <3"

    def test_handles_nested_tags(self):
        """Deeply nested tags should be stripped, retaining the text."""
        processor = HTMLParser()
        ctx = PipelineContext()
        ctx.set("body_html", "<div><ul><li><a href='#'>Link text</a></li></ul></div>")
        result = processor.process(ctx)
        assert result.get("body_text") == "Link text"

    def test_empty_body_html_returns_empty_string(self):
        """When body_html is empty string, body_text should be empty string."""
        processor = HTMLParser()
        ctx = PipelineContext()
        ctx.set("body_html", "")
        result = processor.process(ctx)
        assert result.get("body_text") == ""

    def test_none_body_html_returns_empty_string(self):
        """When body_html is None (not set), body_text should be empty string."""
        processor = HTMLParser()
        ctx = PipelineContext()
        # body_html not set, so context.get("body_html") returns None
        result = processor.process(ctx)
        assert result.get("body_text") == ""

    def test_plain_text_passes_through(self):
        """Input without HTML tags should pass through unchanged."""
        processor = HTMLParser()
        ctx = PipelineContext()
        ctx.set("body_html", "Just plain text")
        result = processor.process(ctx)
        assert result.get("body_text") == "Just plain text"


# ---------------------------------------------------------------------------
# AC-T018-2: ContentDedup
# ---------------------------------------------------------------------------
class TestContentDedup:
    """AC-T018-2: ContentDedup detects duplicate content via SHA-256 fingerprint."""

    def test_new_content_marked_not_duplicate(self):
        """First-time content should be marked as is_duplicate=False."""
        processor = ContentDedup()
        ctx = PipelineContext()
        ctx.set("body_text", "unique content")
        fingerprint = hashlib.sha256("unique content".encode()).hexdigest()
        ctx.set("fingerprint", fingerprint)
        result = processor.process(ctx)
        assert result.get("is_duplicate") is False

    def test_duplicate_content_marked_duplicate(self):
        """Existing-fingerprint content should be marked is_duplicate=True."""
        fingerprint = hashlib.sha256("duplicate content".encode()).hexdigest()
        seen = {fingerprint}
        processor = ContentDedup(seen_fingerprints=seen)
        ctx = PipelineContext()
        ctx.set("body_text", "duplicate content")
        ctx.set("fingerprint", fingerprint)
        result = processor.process(ctx)
        assert result.get("is_duplicate") is True

    def test_new_fingerprint_is_recorded(self):
        """After processing new content, its fingerprint is stored for future dedup."""
        seen: set[str] = set()
        processor = ContentDedup(seen_fingerprints=seen)
        ctx = PipelineContext()
        text = "record me"
        fingerprint = hashlib.sha256(text.encode()).hexdigest()
        ctx.set("body_text", text)
        ctx.set("fingerprint", fingerprint)
        processor.process(ctx)
        assert fingerprint in seen

    def test_fingerprint_uses_sha256(self):
        """The fingerprint should be a valid SHA-256 hex digest."""
        processor = ContentDedup()
        ctx = PipelineContext()
        text = "test sha256"
        expected_fp = hashlib.sha256(text.encode()).hexdigest()
        ctx.set("body_text", text)
        ctx.set("fingerprint", expected_fp)
        result = processor.process(ctx)
        # New content -> not duplicate
        assert result.get("is_duplicate") is False

    def test_sequential_dedup_across_contexts(self):
        """Same fingerprint twice via one processor instance detects duplicate."""
        processor = ContentDedup()
        fingerprint = hashlib.sha256("repeated".encode()).hexdigest()

        ctx1 = PipelineContext()
        ctx1.set("body_text", "repeated")
        ctx1.set("fingerprint", fingerprint)
        result1 = processor.process(ctx1)
        assert result1.get("is_duplicate") is False

        ctx2 = PipelineContext()
        ctx2.set("body_text", "repeated")
        ctx2.set("fingerprint", fingerprint)
        result2 = processor.process(ctx2)
        assert result2.get("is_duplicate") is True


# ---------------------------------------------------------------------------
# AC-T018-3: KeywordTagger
# ---------------------------------------------------------------------------
class TestKeywordTagger:
    """AC-T018-3: KeywordTagger adds tags based on a predefined keyword library."""

    def test_matches_single_keyword(self):
        """Content containing a keyword synonym should receive the corresponding tag."""
        keywords = {"AI": ["artificial intelligence", "machine learning"]}
        processor = KeywordTagger(keywords=keywords)
        ctx = PipelineContext()
        ctx.set(
            "body_text", "Recent advances in artificial intelligence are impressive."
        )
        result = processor.process(ctx)
        tags = result.get("tags")
        assert isinstance(tags, list)
        assert "AI" in tags

    def test_matches_multiple_tags(self):
        """Content matching keywords in multiple categories gets all matching tags."""
        keywords = {
            "AI": ["artificial intelligence"],
            "Cloud": ["cloud computing"],
        }
        processor = KeywordTagger(keywords=keywords)
        ctx = PipelineContext()
        ctx.set(
            "body_text",
            "Artificial intelligence meets cloud computing in new platform.",
        )
        result = processor.process(ctx)
        tags = result.get("tags")
        assert "AI" in tags
        assert "Cloud" in tags

    def test_case_insensitive_matching(self):
        """Keyword matching should be case-insensitive."""
        keywords = {"AI": ["machine learning"]}
        processor = KeywordTagger(keywords=keywords)
        ctx = PipelineContext()
        ctx.set("body_text", "MACHINE LEARNING is transforming industry.")
        result = processor.process(ctx)
        tags = result.get("tags")
        assert "AI" in tags

    def test_no_match_returns_empty_tags(self):
        """When no keywords match, tags should be an empty list."""
        keywords = {"AI": ["artificial intelligence"]}
        processor = KeywordTagger(keywords=keywords)
        ctx = PipelineContext()
        ctx.set("body_text", "The weather is nice today.")
        result = processor.process(ctx)
        tags = result.get("tags")
        assert tags == []

    def test_empty_body_text_returns_empty_tags(self):
        """Empty body_text should produce an empty tags list."""
        keywords = {"AI": ["artificial intelligence"]}
        processor = KeywordTagger(keywords=keywords)
        ctx = PipelineContext()
        ctx.set("body_text", "")
        result = processor.process(ctx)
        tags = result.get("tags")
        assert tags == []

    def test_no_duplicate_tags(self):
        """A tag should appear at most once even if multiple synonyms match."""
        keywords = {"AI": ["artificial intelligence", "AI research"]}
        processor = KeywordTagger(keywords=keywords)
        ctx = PipelineContext()
        ctx.set("body_text", "artificial intelligence and AI research are booming.")
        result = processor.process(ctx)
        tags = result.get("tags")
        assert tags.count("AI") == 1


# ---------------------------------------------------------------------------
# AC-T018-4: FormatConverter
# ---------------------------------------------------------------------------
class TestFormatConverter:
    """AC-T018-4: FormatConverter normalizes content formatting."""

    def test_collapses_multiple_spaces(self):
        """Multiple consecutive spaces should be collapsed to a single space."""
        processor = FormatConverter()
        ctx = PipelineContext()
        ctx.set("body_text", "hello    world")
        result = processor.process(ctx)
        assert result.get("body_text") == "hello world"

    def test_normalizes_line_endings(self):
        r"""Mixed line endings (\r\n, \r) should be normalized to \n."""
        processor = FormatConverter()
        ctx = PipelineContext()
        ctx.set("body_text", "line1\r\nline2\rline3\nline4")
        result = processor.process(ctx)
        body = result.get("body_text")
        assert "\r" not in body
        assert "line1\nline2\nline3\nline4" == body

    def test_strips_leading_trailing_whitespace(self):
        """Leading and trailing whitespace should be removed."""
        processor = FormatConverter()
        ctx = PipelineContext()
        ctx.set("body_text", "   hello world   ")
        result = processor.process(ctx)
        assert result.get("body_text") == "hello world"

    def test_collapses_multiple_blank_lines(self):
        """Multiple consecutive blank lines collapse into a single blank line."""
        processor = FormatConverter()
        ctx = PipelineContext()
        ctx.set("body_text", "paragraph1\n\n\n\nparagraph2")
        result = processor.process(ctx)
        assert result.get("body_text") == "paragraph1\n\nparagraph2"

    def test_combined_cleanup(self):
        """Multiple formatting issues in one input should all be cleaned up."""
        processor = FormatConverter()
        ctx = PipelineContext()
        ctx.set("body_text", "  hello    world  \r\n\r\n\r\n  foo  ")
        result = processor.process(ctx)
        body = result.get("body_text")
        assert "\r" not in body
        # No leading/trailing whitespace
        assert body == body.strip()
        # No consecutive spaces within lines
        assert "  " not in body.split("\n")[0]

    def test_empty_body_text_returns_empty(self):
        """Empty body_text should remain empty after formatting."""
        processor = FormatConverter()
        ctx = PipelineContext()
        ctx.set("body_text", "")
        result = processor.process(ctx)
        assert result.get("body_text") == ""

    def test_returns_pipeline_context(self):
        """process() should return a PipelineContext instance."""
        processor = FormatConverter()
        ctx = PipelineContext()
        ctx.set("body_text", "text")
        result = processor.process(ctx)
        assert isinstance(result, PipelineContext)


# ---------------------------------------------------------------------------
# AC-015 + AC-T018-4: FormatConverter registered and active in content-process
# ---------------------------------------------------------------------------


class TestFormatConverterWired:
    """FormatConverter is registered and runs in the content-process pipeline."""

    def test_format_converter_is_registered(self) -> None:
        """get_processor resolves 'FormatConverter' (AC-015 registrable)."""
        from intellisource.pipeline.registry import get_processor

        assert get_processor("FormatConverter") is FormatConverter

    def test_content_process_runs_format_converter_after_parse(self) -> None:
        """content-process.yaml runs FormatConverter right after HTMLParser."""
        from pathlib import Path

        from intellisource.config.pipeline_models import PipelineConfig

        yaml_path = (
            Path(__file__).resolve().parents[3]
            / "config"
            / "pipelines"
            / "content-process.yaml"
        )
        config = PipelineConfig.from_yaml(str(yaml_path))
        processors = [step.get("processor") for step in config.steps]
        assert "FormatConverter" in processors
        assert processors.index("FormatConverter") == processors.index("HTMLParser") + 1
