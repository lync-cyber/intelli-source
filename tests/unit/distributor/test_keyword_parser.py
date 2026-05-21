"""Tests for keyword_parser and scorer keyword weight integration.

Covers AC-3 and AC-4 of T-093:
- AC-3: distributor/keyword_parser.py provides parse_keyword_token(kw) -> (operator, value)
- AC-4: scorer._keyword_match_score uses parse_keyword_token; '+' weight × 2.0;
        '!' → 0 contribution; '/regex/' → 1.0 weight
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

import pytest


# ---------------------------------------------------------------------------
# Stub helpers for scorer tests
# ---------------------------------------------------------------------------


@dataclass
class StubSubscription:
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    match_rules: dict = field(default_factory=lambda: {"keywords": [], "tags": [], "min_score": 0})
    status: str = "active"


@dataclass
class StubContent:
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    title: str = "Python programming guide"
    body_text: str = "Learn python today"
    tags: list[str] = field(default_factory=list)
    source_credibility: float = 1.0
    published_at: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )


# ===========================================================================
# AC-3: parse_keyword_token correctness
# ===========================================================================


class TestParseKeywordToken:
    def _parse(self, kw: str):
        from intellisource.distributor.keyword_parser import parse_keyword_token

        return parse_keyword_token(kw)

    def test_plus_prefix_returns_required_operator(self):
        """AC-3: '+python' → ('+', 'python')."""
        op, val = self._parse("+python")
        assert op == "+"
        assert val == "python"

    def test_bang_prefix_returns_exclude_operator(self):
        """AC-3: '!java' → ('!', 'java')."""
        op, val = self._parse("!java")
        assert op == "!"
        assert val == "java"

    def test_regex_delimiters_returns_regex_operator(self):
        """AC-3: '/py.*/' → ('regex', 'py.*')."""
        op, val = self._parse("/py.*/")
        assert op == "regex"
        assert val == "py.*"

    def test_plain_word_returns_plain_operator(self):
        """AC-3: 'plain_word' → ('plain', 'plain_word')."""
        op, val = self._parse("plain_word")
        assert op == "plain"
        assert val == "plain_word"

    def test_plain_word_no_special_prefix(self):
        """AC-3: ordinary keyword without prefix → 'plain'."""
        op, val = self._parse("machine_learning")
        assert op == "plain"
        assert val == "machine_learning"

    # -- Security / boundary cases --

    def test_empty_string_does_not_raise(self):
        """AC-3 boundary: empty string is handled gracefully (plain or raises ValueError)."""
        # The parser should either return ('plain', '') or raise a well-typed error.
        # Implementation must not silently produce wrong operator.
        try:
            op, val = self._parse("")
            # If it returns, operator must be 'plain' and value empty
            assert op == "plain"
            assert val == ""
        except (ValueError, IndexError):
            pass  # Explicit error for empty input is also acceptable

    def test_single_plus_only(self):
        """AC-3 boundary: '+' alone → operator '+' with empty value, or 'plain'."""
        op, val = self._parse("+")
        # '+' with empty remainder is either ('+', '') or ('plain', '+')
        assert op in ("+", "plain")

    def test_single_bang_only(self):
        """AC-3 boundary: '!' alone → operator '!' with empty value, or 'plain'."""
        op, val = self._parse("!")
        assert op in ("!", "plain")

    def test_mixed_prefix_plus_bang(self):
        """AC-3 boundary security: '+!both' — first valid prefix wins or treated as plain.
        The parser must be deterministic and not crash.
        """
        op, val = self._parse("+!both")
        # First character is '+' so either ('+', '!both') is the greedy parse,
        # or a strict parser may reject it. Either is acceptable; not silent wrong.
        assert op in ("+", "plain")
        assert isinstance(val, str)

    def test_regex_without_closing_slash_is_plain(self):
        """AC-3 boundary: '/pattern' without closing slash → plain (not regex)."""
        op, val = self._parse("/pattern")
        # No closing slash → cannot be a regex token
        assert op == "plain"

    def test_regex_with_empty_pattern(self):
        """AC-3 boundary: '//' → ('regex', '') — empty regex pattern."""
        op, val = self._parse("//")
        assert op == "regex"
        assert val == ""

    def test_plus_with_spaces_in_value(self):
        """AC-3: '+hello world' → ('+', 'hello world') — value preserves inner content."""
        op, val = self._parse("+hello world")
        assert op == "+"
        assert val == "hello world"


# ===========================================================================
# AC-4: scorer._keyword_match_score uses parse_keyword_token weights
# ===========================================================================


class TestScorerKeywordWeights:
    def _scorer(self):
        from intellisource.distributor.scorer import ContentScorer

        return ContentScorer()

    def test_required_keyword_hit_scores_double_plain(self):
        """AC-4: '+python' hit → score higher than 'python' plain hit (weight × 2.0)."""
        scorer = self._scorer()
        content = StubContent(title="python guide", body_text="")

        sub_plain = StubSubscription(
            match_rules={"keywords": ["python"], "tags": [], "min_score": 0}
        )
        sub_required = StubSubscription(
            match_rules={"keywords": ["+python"], "tags": [], "min_score": 0}
        )

        score_plain = scorer._keyword_match_score(content, sub_plain)
        score_required = scorer._keyword_match_score(content, sub_required)

        assert score_required > score_plain, (
            f"'+python' hit score ({score_required}) should exceed "
            f"'python' plain score ({score_plain})"
        )

    def test_exclude_keyword_hit_contributes_zero(self):
        """AC-4: '!java' match → contributes 0, not negative."""
        scorer = self._scorer()
        content = StubContent(title="java programming", body_text="")

        sub_exclude = StubSubscription(
            match_rules={"keywords": ["!java"], "tags": [], "min_score": 0}
        )

        score = scorer._keyword_match_score(content, sub_exclude)
        assert score == 0.0, f"Excluded keyword match should contribute 0, got {score}"

    def test_regex_keyword_hit_scores_one_weight(self):
        """AC-4: '/py.*/' match → contributes 1.0 weight (× 1.0)."""
        scorer = self._scorer()
        content = StubContent(title="python programming", body_text="")

        sub_regex = StubSubscription(
            match_rules={"keywords": ["/py.*/"], "tags": [], "min_score": 0}
        )
        sub_plain = StubSubscription(
            match_rules={"keywords": ["python"], "tags": [], "min_score": 0}
        )

        score_regex = scorer._keyword_match_score(content, sub_regex)
        score_plain = scorer._keyword_match_score(content, sub_plain)

        # regex hit weight (× 1.0) should equal plain weight (× 1.0) for same single keyword
        assert score_regex == pytest.approx(score_plain, rel=0.01), (
            f"regex match score ({score_regex}) should equal plain match score ({score_plain})"
        )

    def test_required_keyword_weight_is_double_plain_exact_ratio(self):
        """AC-4: for single keyword, required hit is exactly 2× plain hit."""
        scorer = self._scorer()
        content = StubContent(title="python guide", body_text="")

        sub_plain = StubSubscription(
            match_rules={"keywords": ["python"], "tags": [], "min_score": 0}
        )
        sub_required = StubSubscription(
            match_rules={"keywords": ["+python"], "tags": [], "min_score": 0}
        )

        score_plain = scorer._keyword_match_score(content, sub_plain)
        score_required = scorer._keyword_match_score(content, sub_required)

        assert score_required == pytest.approx(score_plain * 2.0, rel=0.01)

    def test_no_keywords_returns_zero(self):
        """AC-4: empty keywords list → 0.0."""
        scorer = self._scorer()
        content = StubContent(title="python guide", body_text="")
        sub = StubSubscription(
            match_rules={"keywords": [], "tags": [], "min_score": 0}
        )
        assert scorer._keyword_match_score(content, sub) == 0.0
