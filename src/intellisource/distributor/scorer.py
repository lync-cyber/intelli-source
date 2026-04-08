"""ContentScorer for weighted content scoring."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any


class ContentScorer:
    """Scores content relevance for a subscription."""

    def score(self, content: Any, subscription: Any) -> float:
        """Compute weighted score = credibility * time_decay * keyword_match."""
        credibility: float = getattr(content, "source_credibility", 0.0)
        if credibility == 0.0:
            return 0.0

        time_decay = self._time_decay(content)
        keyword_score = self._keyword_match_score(content, subscription)

        return float(credibility * time_decay * keyword_score)

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
        """Fraction of keywords matched in content text."""
        rules = getattr(subscription, "match_rules", {})
        keywords: list[str] = rules.get("keywords", [])
        if not keywords:
            return 0.0

        text = (
            getattr(content, "title", "") + " " + getattr(content, "body_text", "")
        ).lower()

        matched = sum(1 for kw in keywords if kw.lower() in text)
        return matched / len(keywords)
