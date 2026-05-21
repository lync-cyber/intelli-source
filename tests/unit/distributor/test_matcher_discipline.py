"""Tests for SubscriptionMatcher discipline_tags vs tags weight distinction.

Covers AC-6 of T-093:
- matcher.py distinguishes 'tags' and 'discipline_tags' in matching
- discipline_tags match carries higher weight than generic tags match
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Stub helpers
# ---------------------------------------------------------------------------


@dataclass
class StubSubscription:
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    match_rules: dict = field(
        default_factory=lambda: {
            "keywords": [],
            "tags": [],
            "discipline_tags": [],
            "min_score": 0,
        }
    )
    status: str = "active"
    timezone: str = "Asia/Shanghai"


@dataclass
class StubContent:
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    title: str = "Test article"
    body_text: str = "some content"
    tags: list[str] = field(default_factory=list)
    discipline_tags: list[str] = field(default_factory=list)
    source_credibility: float = 1.0
    published_at: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )


# ===========================================================================
# AC-6: discipline_tags matching in SubscriptionMatcher
# ===========================================================================


class TestMatcherDisciplineTagsDistinction:
    def _matcher(self):
        from intellisource.distributor.matcher import SubscriptionMatcher

        return SubscriptionMatcher()

    def test_content_discipline_tags_match_subscription_discipline_tags(self):
        """AC-6: content.discipline_tags ∩ sub.match_rules.discipline_tags → match."""
        matcher = self._matcher()
        content = StubContent(
            title="quantum computing paper",
            body_text="",
            discipline_tags=["physics", "quantum"],
        )
        sub = StubSubscription(
            match_rules={
                "keywords": [],
                "tags": [],
                "discipline_tags": ["quantum"],
                "min_score": 0,
            }
        )
        results = matcher.match(content, [sub])
        assert sub in results, (
            "Subscription with matching discipline_tags should be returned"
        )

    def test_discipline_tags_do_not_match_generic_tags(self):
        """AC-6: content.tags do not satisfy subscription.discipline_tags rules."""
        matcher = self._matcher()
        content = StubContent(
            title="quantum paper",
            body_text="",
            tags=["quantum"],  # generic tag only
            discipline_tags=[],  # no discipline tags
        )
        sub = StubSubscription(
            match_rules={
                "keywords": [],
                "tags": [],
                "discipline_tags": ["quantum"],  # only discipline_tags required
                "min_score": 0,
            }
        )
        results = matcher.match(content, [sub])
        # Generic content.tags must NOT satisfy discipline_tags requirement
        assert sub not in results, (
            "content.tags=['quantum'] must not satisfy discipline_tags=['quantum']"
        )

    def test_generic_tags_still_work_independently(self):
        """AC-6: content.tags match subscription.tags → match (legacy behavior)."""
        matcher = self._matcher()
        content = StubContent(
            title="machine learning",
            body_text="",
            tags=["ml", "ai"],
            discipline_tags=[],
        )
        sub = StubSubscription(
            match_rules={
                "keywords": [],
                "tags": ["ml"],
                "discipline_tags": [],
                "min_score": 0,
            }
        )
        results = matcher.match(content, [sub])
        assert sub in results, (
            "content.tags['ml'] should still match match_rules.tags=['ml']"
        )

    def test_discipline_tags_score_higher_than_generic_tags(self):
        """AC-6: discipline_tags match produces higher score than generic tags match."""
        from intellisource.distributor.scorer import ContentScorer

        scorer = ContentScorer()

        content_generic = StubContent(
            title="python programming",
            body_text="",
            tags=["python"],
            discipline_tags=[],
            source_credibility=1.0,
        )
        content_discipline = StubContent(
            title="python programming",
            body_text="",
            tags=[],
            discipline_tags=["python"],
            source_credibility=1.0,
        )

        sub = StubSubscription(
            match_rules={
                "keywords": ["python"],
                "tags": ["python"],
                "discipline_tags": ["python"],
                "min_score": 0,
            }
        )

        score_generic = scorer.score(content_generic, sub)
        score_discipline = scorer.score(content_discipline, sub)

        assert score_discipline > score_generic, (
            f"discipline_tags match score ({score_discipline}) should be higher than "
            f"generic tags match score ({score_generic})"
        )

    def test_no_tags_no_discipline_tags_no_keywords_no_match(self):
        """AC-6: subscription has discipline_tags but content has none → no match."""
        matcher = self._matcher()
        content = StubContent(
            title="random article",
            body_text="nothing relevant",
            tags=[],
            discipline_tags=[],
        )
        sub = StubSubscription(
            match_rules={
                "keywords": [],
                "tags": [],
                "discipline_tags": ["physics"],
                "min_score": 0,
            }
        )
        results = matcher.match(content, [sub])
        assert sub not in results

    def test_both_tags_and_discipline_tags_can_match(self):
        """AC-6: content matching both tags and discipline_tags is returned."""
        matcher = self._matcher()
        content = StubContent(
            title="ai and quantum research",
            body_text="",
            tags=["ai"],
            discipline_tags=["quantum"],
        )
        sub = StubSubscription(
            match_rules={
                "keywords": [],
                "tags": ["ai"],
                "discipline_tags": ["quantum"],
                "min_score": 0,
            }
        )
        results = matcher.match(content, [sub])
        assert sub in results

    def test_discipline_tags_empty_list_in_match_rules(self):
        """AC-6: empty discipline_tags in match_rules → discipline match skipped."""
        matcher = self._matcher()
        content = StubContent(
            title="test article",
            body_text="machine learning content",
            tags=["ml"],
            discipline_tags=["physics"],
        )
        sub = StubSubscription(
            match_rules={
                "keywords": [],
                "tags": ["ml"],
                "discipline_tags": [],  # no discipline filter
                "min_score": 0,
            }
        )
        results = matcher.match(content, [sub])
        assert sub in results, (
            "empty discipline_tags filter should not block a match via generic tags"
        )
