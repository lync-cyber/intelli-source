"""ContentScorer for weighted content scoring."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

import regex as regex_lib

from intellisource.distributor.keyword_parser import parse_keyword_token

_DISCIPLINE_TAG_WEIGHT = 2.0
_GENERIC_TAG_WEIGHT = 1.0


class ContentScorer:
    """Scores content relevance for a subscription."""

    def score(self, content: Any, subscription: Any) -> float:
        """Compute weighted score = credibility * time_decay * keyword_match."""
        credibility: float = getattr(content, "source_credibility", 0.0)
        if credibility == 0.0:
            return 0.0

        time_decay = self._time_decay(content)
        keyword_score = self._keyword_match_score(content, subscription)
        tag_score = self._tag_match_score(content, subscription)

        return float(credibility * time_decay * (keyword_score + tag_score))

    def rank(self, contents: list[Any], subscription: Any) -> list[Any]:
        """Return contents sorted by score descending."""
        return sorted(
            contents,
            key=lambda c: self.score(c, subscription),
            reverse=True,
        )

    def filter_by_threshold(self, contents: list[Any], subscription: Any) -> list[Any]:
        """Filter contents by min_score threshold."""
        rules = getattr(subscription, "match_rules", {})
        min_score: float = rules.get("min_score", 0)
        if min_score == 0:
            return list(contents)
        return [c for c in contents if self.score(c, subscription) >= min_score]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _time_decay(content: Any) -> float:
        """Exponential decay based on content age in days."""
        published_at: datetime = getattr(
            content,
            "published_at",
            datetime.now(tz=timezone.utc),
        )
        now = datetime.now(tz=timezone.utc)
        age_days = max((now - published_at).total_seconds() / 86400.0, 0.0)
        # Half-life of 7 days
        return float(math.exp(-0.1 * age_days))

    @staticmethod
    def _keyword_match_score(content: Any, subscription: Any) -> float:
        """Weighted keyword match score using parse_keyword_token.

        Operator weights:
        - ``+`` (required): hit contributes × 2.0
        - ``!`` (exclude): hit contributes 0 (no negative score)
        - ``regex``: hit contributes × 1.0
        - ``plain``: hit contributes × 1.0
        """
        rules = getattr(subscription, "match_rules", {})
        keywords: list[str] = rules.get("keywords", [])
        if not keywords:
            return 0.0

        text = getattr(content, "title", "") + " " + getattr(content, "body_text", "")
        text_lower = text.lower()

        total_weight = 0.0

        for kw in keywords:
            operator, value = parse_keyword_token(kw)

            if operator == "+":
                if value.lower() in text_lower:
                    total_weight += 2.0
            elif operator == "!":
                # hit contributes 0; exclusion logic is handled by matcher
                pass
            elif operator == "regex":
                try:
                    if regex_lib.search(value, text, timeout=1.0):
                        total_weight += 1.0
                except TimeoutError:
                    pass
            else:
                if value.lower() in text_lower:
                    total_weight += 1.0

        return total_weight / len(keywords)

    @staticmethod
    def _tag_match_score(content: Any, subscription: Any) -> float:
        """Tag match score distinguishing discipline_tags from generic tags."""
        rules = getattr(subscription, "match_rules", {})
        sub_tags: set[str] = set(rules.get("tags", []))
        sub_discipline_tags: set[str] = set(rules.get("discipline_tags", []))

        content_tags: set[str] = set(getattr(content, "tags", []))
        content_discipline_tags: set[str] = set(getattr(content, "discipline_tags", []))

        score = 0.0
        if sub_discipline_tags:
            hits = content_discipline_tags & sub_discipline_tags
            score += len(hits) * _DISCIPLINE_TAG_WEIGHT
        if sub_tags:
            hits = content_tags & sub_tags
            score += len(hits) * _GENERIC_TAG_WEIGHT
        return score
