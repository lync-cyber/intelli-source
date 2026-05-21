"""SubscriptionMatcher and DeliveryTracker."""

from __future__ import annotations

import logging
import uuid
from typing import Any

import regex as regex_lib

from intellisource.distributor.keyword_parser import parse_keyword_token
from intellisource.distributor.scorer import ContentScorer

_logger = logging.getLogger(__name__)


class SubscriptionMatcher:
    """Matches content against subscription rules."""

    def __init__(self) -> None:
        self._scorer = ContentScorer()

    def match(self, content: Any, subscriptions: list[Any]) -> list[Any]:
        """Return subscriptions whose rules match the given content."""
        results: list[Any] = []
        for sub in subscriptions:
            if getattr(sub, "status", "active") != "active":
                continue
            if self._matches(content, sub):
                results.append(sub)
        return results

    def _matches(self, content: Any, subscription: Any) -> bool:
        """Check if content matches a single subscription's rules."""
        rules = getattr(subscription, "match_rules", {})
        keywords: list[str] = rules.get("keywords", [])
        tags: list[str] = rules.get("tags", [])
        discipline_tags: list[str] = rules.get("discipline_tags", [])
        min_score: float = rules.get("min_score", 0)

        if not keywords and not tags and not discipline_tags:
            return False

        text = getattr(content, "title", "") + " " + getattr(content, "body_text", "")
        text_lower = text.lower()

        # Keyword constraint evaluation
        has_keyword_match = self._evaluate_keywords(keywords, text, text_lower)
        if has_keyword_match is None:
            # A required/excluded constraint was violated
            return False

        # Generic tag matching
        content_tags: set[str] = set(getattr(content, "tags", []))
        has_tag_match = bool(content_tags & set(tags))

        # Discipline tag matching (separate from generic tags)
        content_discipline_tags: set[str] = set(getattr(content, "discipline_tags", []))
        has_discipline_tag_match = bool(
            discipline_tags and (content_discipline_tags & set(discipline_tags))
        )

        if not has_keyword_match and not has_tag_match and not has_discipline_tag_match:
            return False

        # min_score filtering
        if min_score > 0:
            score = self._scorer.score(content, subscription)
            if score < min_score:
                return False

        return True

    @staticmethod
    def _evaluate_keywords(
        keywords: list[str],
        text: str,
        text_lower: str,
    ) -> bool | None:
        """Evaluate keyword constraints against content text.

        Returns ``True`` if at least one positive keyword matched,
        ``False`` if no positive keyword matched (but no constraint
        was violated), or ``None`` if a required/excluded constraint
        was violated (meaning the match should be rejected).

        The ``/regex/`` branch uses ``regex.search(pattern, text, timeout=1.0)``
        for ReDoS protection; ``TimeoutError`` is caught, logged, and treated
        as no-match for that keyword.
        """
        has_match = False

        for kw in keywords:
            operator, value = parse_keyword_token(kw)

            if operator == "+":
                if value.lower() not in text_lower:
                    return None
                has_match = True
            elif operator == "!":
                if value.lower() in text_lower:
                    return None
            elif operator == "regex":
                try:
                    if regex_lib.search(value, text, timeout=1.0):
                        has_match = True
                except TimeoutError:
                    _logger.warning(
                        "regex.search timeout for pattern %r — treating as no-match",
                        value,
                    )
            else:
                if value.lower() in text_lower:
                    has_match = True

        return has_match


class DeliveryTracker:
    """Tracks push delivery history for deduplication."""

    def __init__(self) -> None:
        self._pushed: set[tuple[uuid.UUID, uuid.UUID, str]] = set()

    def record(
        self,
        *,
        content_id: uuid.UUID,
        subscription_id: uuid.UUID,
        channel: str = "",
    ) -> None:
        """Record a push delivery."""
        self._pushed.add((content_id, subscription_id, channel))

    def has_been_pushed(
        self,
        *,
        content_id: uuid.UUID,
        subscription_id: uuid.UUID,
        channel: str = "",
    ) -> bool:
        """Check if content has been pushed to subscription on channel."""
        return (content_id, subscription_id, channel) in self._pushed

    def is_duplicate(
        self,
        *,
        content_id: uuid.UUID,
        subscription_id: uuid.UUID,
        channel: str = "",
    ) -> bool:
        """Check if pushing would be a duplicate."""
        return self.has_been_pushed(
            content_id=content_id,
            subscription_id=subscription_id,
            channel=channel,
        )
