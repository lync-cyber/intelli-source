"""Tests for atomic tool functions in pipeline/processors/tools.py.

Covers all 10 async tool functions with at least 3 tests each:
normal use, edge cases, and empty/boundary input.
"""

from __future__ import annotations

import hashlib
from types import SimpleNamespace
from typing import Any

from intellisource.pipeline.processors.tools import (
    filter_sensitive,
    find_nearest_cluster,
    fingerprint_dedup,
    fingerprint_generate,
    keyword_tag,
    regex_extract,
    tfidf_keywords,
    truncate_for_push,
    truncate_summary,
    vector_search_similar,
)


# ---------------------------------------------------------------------------
# 1. regex_extract
# ---------------------------------------------------------------------------
class TestRegexExtract:
    """Tests for regex_extract function."""

    async def test_default_patterns_extract_all_fields(self) -> None:
        """Default patterns extract title, authors, keywords, date."""
        text = (
            "Title: My Paper\n"
            "Authors: Alice, Bob\n"
            "Keywords: NLP, AI, ML\n"
            "Date: 2024-01-01"
        )
        result = await regex_extract(text)
        assert result["title"] == "My Paper"
        assert result["authors"] == ["Alice", "Bob"]
        assert result["keywords"] == ["NLP", "AI", "ML"]
        assert result["date"] == "2024-01-01"

    async def test_default_patterns_partial_match(self) -> None:
        """Only matched fields are returned when not all patterns match."""
        text = "Title: Only Title Here"
        result = await regex_extract(text)
        assert result["title"] == "Only Title Here"
        assert "authors" not in result
        assert "keywords" not in result
        assert "date" not in result

    async def test_empty_body_text(self) -> None:
        """Empty input returns empty dict."""
        result = await regex_extract("")
        assert result == {}

    async def test_custom_patterns(self) -> None:
        """Custom patterns extract user-defined fields."""
        text = "Version: 3.2.1\nLicense: MIT"
        patterns: list[dict[str, Any]] = [
            {"field": "version", "pattern": r"Version:\s*(.+)", "is_list": False},
            {"field": "license", "pattern": r"License:\s*(.+)", "is_list": False},
        ]
        result = await regex_extract(text, patterns=patterns)
        assert result["version"] == "3.2.1"
        assert result["license"] == "MIT"

    async def test_custom_pattern_with_is_list(self) -> None:
        """Custom pattern with is_list splits on commas."""
        text = "Tags: foo, bar, baz"
        patterns: list[dict[str, Any]] = [
            {"field": "tags", "pattern": r"Tags:\s*(.+)", "is_list": True},
        ]
        result = await regex_extract(text, patterns=patterns)
        assert result["tags"] == ["foo", "bar", "baz"]


# ---------------------------------------------------------------------------
# 2. fingerprint_generate
# ---------------------------------------------------------------------------
class TestFingerprintGenerate:
    """Tests for fingerprint_generate function."""

    async def test_returns_64_char_hex(self) -> None:
        """Result is a 64-character lowercase hex string."""
        fp = await fingerprint_generate("hello", "world")
        assert len(fp) == 64
        assert all(c in "0123456789abcdef" for c in fp)

    async def test_deterministic(self) -> None:
        """Same input always produces the same fingerprint."""
        fp1 = await fingerprint_generate("title", "body")
        fp2 = await fingerprint_generate("title", "body")
        assert fp1 == fp2

    async def test_whitespace_normalization(self) -> None:
        """Extra whitespace is collapsed, so fingerprints match."""
        fp1 = await fingerprint_generate("  Hello  World ", "  foo  bar ")
        fp2 = await fingerprint_generate("Hello World", "foo bar")
        assert fp1 == fp2

    async def test_empty_inputs(self) -> None:
        """Empty strings produce a valid SHA-256 hash of empty normalized text."""
        fp = await fingerprint_generate("", "")
        expected = hashlib.sha256(b"").hexdigest()
        assert fp == expected


# ---------------------------------------------------------------------------
# 3. vector_search_similar
# ---------------------------------------------------------------------------
class TestVectorSearchSimilar:
    """Tests for vector_search_similar function."""

    async def test_returns_list_of_dicts(self) -> None:
        """Each candidate is mapped to a dict with id, score, title, body_text."""
        candidates = [
            SimpleNamespace(id="1", score=0.95, title="Doc1", body_text="text1"),
            SimpleNamespace(id="2", score=0.85, title="Doc2", body_text="text2"),
        ]

        class MockStore:
            def search_similar(
                self, embedding: list[float], *, threshold: float
            ) -> list[Any]:
                return candidates

        result = await vector_search_similar([0.1, 0.2], 0.8, MockStore())
        assert len(result) == 2
        assert result[0] == {
            "id": "1",
            "score": 0.95,
            "title": "Doc1",
            "body_text": "text1",
        }

    async def test_empty_results(self) -> None:
        """When no candidates match, returns empty list."""

        class MockStore:
            def search_similar(
                self, embedding: list[float], *, threshold: float
            ) -> list[Any]:
                return []

        result = await vector_search_similar([0.1], 0.9, MockStore())
        assert result == []

    async def test_missing_attributes_use_defaults(self) -> None:
        """Candidates missing attributes get default values via getattr."""
        candidate = SimpleNamespace()  # no id, score, title, body_text

        class MockStore:
            def search_similar(
                self, embedding: list[float], *, threshold: float
            ) -> list[Any]:
                return [candidate]

        result = await vector_search_similar([0.5], 0.5, MockStore())
        assert result[0]["id"] is None
        assert result[0]["score"] is None
        assert result[0]["title"] == ""
        assert result[0]["body_text"] == ""


# ---------------------------------------------------------------------------
# 4. fingerprint_dedup
# ---------------------------------------------------------------------------
class TestFingerprintDedup:
    """Tests for fingerprint_dedup function."""

    async def test_duplicate_detected(self) -> None:
        """When fingerprint is in known list, is_duplicate is True."""
        fp = await fingerprint_generate("t", "b")
        result = await fingerprint_dedup("t", "b", [fp])
        assert result["is_duplicate"] is True
        assert result["fingerprint"] == fp

    async def test_not_duplicate(self) -> None:
        """When fingerprint is not in known list, is_duplicate is False."""
        result = await fingerprint_dedup("unique", "content", ["abc123"])
        assert result["is_duplicate"] is False
        assert len(result["fingerprint"]) == 64

    async def test_empty_known_list(self) -> None:
        """Empty known fingerprints means nothing is duplicate."""
        result = await fingerprint_dedup("x", "y", [])
        assert result["is_duplicate"] is False


# ---------------------------------------------------------------------------
# 5. find_nearest_cluster
# ---------------------------------------------------------------------------
class TestFindNearestCluster:
    """Tests for find_nearest_cluster function."""

    async def test_returns_cluster_id(self) -> None:
        """When a cluster is found, returns dict with id."""
        cluster = SimpleNamespace(id="cluster-42")

        class MockStore:
            def find_nearest_cluster(
                self, embedding: list[float], *, threshold: float
            ) -> Any:
                return cluster

        result = await find_nearest_cluster([0.1, 0.2], 0.7, MockStore())
        assert result == {"id": "cluster-42"}

    async def test_returns_none_when_no_match(self) -> None:
        """When no cluster matches, returns None."""

        class MockStore:
            def find_nearest_cluster(
                self, embedding: list[float], *, threshold: float
            ) -> None:
                return None

        result = await find_nearest_cluster([0.1], 0.9, MockStore())
        assert result is None

    async def test_cluster_without_id_attribute(self) -> None:
        """If cluster object has no id attribute, returns None for id."""
        cluster = SimpleNamespace()  # no id attribute

        class MockStore:
            def find_nearest_cluster(
                self, embedding: list[float], *, threshold: float
            ) -> Any:
                return cluster

        result = await find_nearest_cluster([0.5], 0.5, MockStore())
        assert result is not None
        assert result["id"] is None


# ---------------------------------------------------------------------------
# 6. tfidf_keywords
# ---------------------------------------------------------------------------
class TestTfidfKeywords:
    """Tests for tfidf_keywords function."""

    async def test_extracts_top_keywords(self) -> None:
        """Returns space-separated top keywords excluding stop words."""
        result = await tfidf_keywords(
            "Machine Learning",
            "machine learning is a subset of AI and machine learning",
        )
        assert "machine" in result.split()
        assert "learning" in result.split()
        # stop words should not appear
        assert "is" not in result.split()
        assert "a" not in result.split()

    async def test_max_five_keywords(self) -> None:
        """Returns at most 5 keywords."""
        text = "alpha beta gamma delta epsilon zeta eta theta iota kappa"
        result = await tfidf_keywords("extra", text)
        assert len(result.split()) <= 5

    async def test_empty_text_returns_title(self) -> None:
        """When body has no valid words, falls back to title."""
        result = await tfidf_keywords("FallbackTitle", "")
        assert result == "fallbacktitle"

    async def test_all_stop_words_returns_title(self) -> None:
        """When all words are stop words, returns title."""
        result = await tfidf_keywords("MyTitle", "the a an is are was")
        assert result == "mytitle"

    async def test_both_empty_returns_unknown(self) -> None:
        """When title and body are both empty, returns 'unknown'."""
        result = await tfidf_keywords("", "")
        assert result == "unknown"


# ---------------------------------------------------------------------------
# 7. truncate_summary
# ---------------------------------------------------------------------------
class TestTruncateSummary:
    """Tests for truncate_summary function."""

    async def test_basic_cluster(self) -> None:
        """Extracts title and summary from cluster contents."""
        contents = [
            {
                "title": "First Doc",
                "body_text": "Sentence one. Sentence two. Sentence three. Four.",
            },
        ]
        result = await truncate_summary(contents)
        assert result["title"] == "First Doc"
        assert "Sentence one" in result["summary"]
        assert "Sentence two" in result["summary"]
        assert "Sentence three" in result["summary"]
        assert result["timeline"] == []
        assert result["key_points"] == []

    async def test_empty_cluster_contents(self) -> None:
        """Empty list returns empty fields."""
        result = await truncate_summary([])
        assert result["title"] == ""
        assert result["summary"] == ""
        assert result["timeline"] == []
        assert result["key_points"] == []

    async def test_multiple_docs_combined(self) -> None:
        """Body texts from multiple docs are combined."""
        contents = [
            {"title": "Main Title", "body_text": "First doc text."},
            {"title": "Other", "body_text": "Second doc text."},
        ]
        result = await truncate_summary(contents)
        assert result["title"] == "Main Title"
        # Combined text: "First doc text. Second doc text."
        assert "First doc text" in result["summary"]

    async def test_summary_ends_with_period(self) -> None:
        """Summary ends with a period if it does not already."""
        contents = [{"title": "T", "body_text": "No period at end"}]
        result = await truncate_summary(contents)
        assert result["summary"].endswith(".")


# ---------------------------------------------------------------------------
# 8. keyword_tag
# ---------------------------------------------------------------------------
class TestKeywordTag:
    """Tests for keyword_tag function."""

    async def test_matches_tags_from_library(self) -> None:
        """Returns tags that appear in body_text or title."""
        result = await keyword_tag(
            "Python is great", "Learn Python", ["Python", "Java"]
        )
        assert "Python" in result
        assert "Java" not in result

    async def test_no_match_returns_uncategorized(self) -> None:
        """When no tag matches, returns ['未分类']."""
        result = await keyword_tag("nothing relevant", "no match", ["Rust", "Go"])
        assert result == ["\u672a\u5206\u7c7b"]

    async def test_empty_body_and_title(self) -> None:
        """Empty body and title: only tags that match empty+space+empty."""
        result = await keyword_tag("", "", ["Python"])
        assert result == ["\u672a\u5206\u7c7b"]

    async def test_tag_in_title_only(self) -> None:
        """A tag appearing only in the title should still match."""
        result = await keyword_tag("unrelated body", "AI News", ["AI", "ML"])
        assert "AI" in result


# ---------------------------------------------------------------------------
# 9. filter_sensitive
# ---------------------------------------------------------------------------
class TestFilterSensitive:
    """Tests for filter_sensitive function."""

    async def test_finds_sensitive_words(self) -> None:
        """Matched sensitive words are returned."""
        result = await filter_sensitive(
            "This is Secret and Classified info", ["secret", "classified"]
        )
        assert "secret" in result
        assert "classified" in result

    async def test_case_insensitive(self) -> None:
        """Matching is case-insensitive."""
        result = await filter_sensitive("SECRET data", ["secret"])
        assert result == ["secret"]

    async def test_empty_text_returns_empty(self) -> None:
        """Empty text returns empty list."""
        result = await filter_sensitive("", ["secret"])
        assert result == []

    async def test_no_match(self) -> None:
        """When no sensitive words match, returns empty list."""
        result = await filter_sensitive("all clear", ["bomb", "attack"])
        assert result == []

    async def test_empty_sensitive_list(self) -> None:
        """Empty sensitive words list returns empty list."""
        result = await filter_sensitive("some text", [])
        assert result == []


# ---------------------------------------------------------------------------
# 10. truncate_for_push
# ---------------------------------------------------------------------------
class TestTruncateForPush:
    """Tests for truncate_for_push function."""

    async def test_short_inputs_unchanged(self) -> None:
        """Short title and body are returned as-is."""
        result = await truncate_for_push("Short Title", "Short body text.")
        assert result["title"] == "Short Title"
        assert result["summary"] == "Short body text."

    async def test_title_truncated_at_80(self) -> None:
        """Title longer than 80 chars is truncated."""
        long_title = "A" * 100
        result = await truncate_for_push(long_title, "body")
        assert len(result["title"]) == 80
        assert result["title"] == "A" * 80

    async def test_summary_truncated_at_200(self) -> None:
        """Summary longer than 200 chars is truncated with ellipsis."""
        long_body = "Word " * 100  # well over 200 chars
        result = await truncate_for_push("Title", long_body)
        assert len(result["summary"]) <= 203  # 200 + "..."

    async def test_empty_inputs(self) -> None:
        """Empty title and body produce empty strings."""
        result = await truncate_for_push("", "")
        assert result["title"] == ""
        assert result["summary"] == ""
