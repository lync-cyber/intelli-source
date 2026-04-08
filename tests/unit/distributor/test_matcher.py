"""Tests for SubscriptionMatcher, BaseDistributor, and DeliveryTracker.

Covers:
- AC-043: SubscriptionMatcher matches content to subscriptions by keywords/tags
- AC-T031-1: BaseDistributor defines distribute(content, subscription)
             -> PushRecord
- AC-T031-2: SubscriptionMatcher.match(content) returns matching Subscriptions
- AC-T031-3: Match rules support keywords (OR) and tags (OR)
- AC-T031-4: Advanced keyword syntax: plain, +required, !excluded, /regex/
- AC-T031-6: min_score threshold filtering (tested partly here for matcher
             integration)
- AC-T031-7: DeliveryTracker records push history and deduplication
"""

from __future__ import annotations

import abc
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

import pytest

# ---------------------------------------------------------------------------
# Lightweight stub data models (no SQLAlchemy dependency)
# ---------------------------------------------------------------------------


@dataclass
class StubSubscription:
    """Minimal Subscription for testing."""

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    name: str = "test-sub"
    source_id: uuid.UUID | None = None
    channel: str = "email"
    channel_config: dict = field(default_factory=dict)
    match_rules: dict = field(
        default_factory=lambda: {
            "keywords": [],
            "tags": [],
            "min_score": 0,
        }
    )
    frequency: str = "realtime"
    quiet_hours: dict = field(default_factory=dict)
    status: str = "active"


@dataclass
class StubContent:
    """Minimal content object for testing."""

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    title: str = "Test Article"
    body_text: str = "Some content body"
    tags: list[str] = field(default_factory=list)
    source_id: uuid.UUID = field(default_factory=uuid.uuid4)
    source_credibility: float = 1.0
    published_at: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )


@dataclass
class StubPushRecord:
    """Minimal PushRecord for testing."""

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    subscription_id: uuid.UUID = field(default_factory=uuid.uuid4)
    content_id: uuid.UUID = field(default_factory=uuid.uuid4)
    channel: str = "email"
    status: str = "pending"
    retry_count: int = 0
    error_message: str = ""
    sent_at: datetime | None = None
    delivered_at: datetime | None = None


# ===================================================================
# AC-T031-1: BaseDistributor defines distribute() -> PushRecord
# ===================================================================


class TestBaseDistributorInterface:
    """Verify BaseDistributor is an ABC with distribute() method."""

    def test_import_base_distributor(self):
        """BaseDistributor can be imported from distributor.base."""
        from intellisource.distributor.base import BaseDistributor  # noqa: F811

        assert BaseDistributor is not None

    def test_base_distributor_is_abstract(self):
        """BaseDistributor cannot be instantiated directly."""
        from intellisource.distributor.base import BaseDistributor

        assert issubclass(BaseDistributor, abc.ABC)
        with pytest.raises(TypeError):
            BaseDistributor()  # type: ignore[abstract]

    def test_distribute_is_abstract_method(self):
        """The distribute method must be declared abstract."""
        from intellisource.distributor.base import BaseDistributor

        assert "distribute" in getattr(BaseDistributor, "__abstractmethods__", set())

    def test_distribute_signature_accepts_content_and_subscription(self):
        """distribute() should accept (content, subscription) args."""
        import inspect

        from intellisource.distributor.base import BaseDistributor

        sig = inspect.signature(BaseDistributor.distribute)
        params = list(sig.parameters.keys())
        # Expect self, content, subscription (names may vary)
        assert len(params) >= 3, (
            "distribute() should accept at least (self, content, subscription)"
        )


# ===================================================================
# AC-T031-2: SubscriptionMatcher.match(content) -> list[Subscription]
# ===================================================================


class TestSubscriptionMatcherBasic:
    """Verify SubscriptionMatcher.match() returns matched subs."""

    def test_import_subscription_matcher(self):
        """SubscriptionMatcher can be imported from distributor.matcher."""
        from intellisource.distributor.matcher import (  # noqa: F811
            SubscriptionMatcher,
        )

        assert SubscriptionMatcher is not None

    def test_match_returns_list(self):
        """match(content) should return a list."""
        from intellisource.distributor.matcher import (
            SubscriptionMatcher,
        )

        matcher = SubscriptionMatcher()
        content = StubContent(title="Python tutorial", body_text="Learn Python")
        sub = StubSubscription(
            match_rules={"keywords": ["Python"], "tags": [], "min_score": 0}
        )
        result = matcher.match(content, [sub])
        assert isinstance(result, list)

    def test_match_returns_matching_subscription(self):
        """match() returns subscriptions whose rules match content."""
        from intellisource.distributor.matcher import (
            SubscriptionMatcher,
        )

        matcher = SubscriptionMatcher()
        content = StubContent(
            title="Python tutorial",
            body_text="Learn Python programming",
        )
        sub_match = StubSubscription(
            name="python-sub",
            match_rules={
                "keywords": ["Python"],
                "tags": [],
                "min_score": 0,
            },
        )
        sub_no_match = StubSubscription(
            name="java-sub",
            match_rules={
                "keywords": ["Java"],
                "tags": [],
                "min_score": 0,
            },
        )
        result = matcher.match(content, [sub_match, sub_no_match])
        matched_names = [s.name for s in result]
        assert "python-sub" in matched_names
        assert "java-sub" not in matched_names

    def test_match_empty_subscriptions_returns_empty(self):
        """match() with no subscriptions returns empty list."""
        from intellisource.distributor.matcher import (
            SubscriptionMatcher,
        )

        matcher = SubscriptionMatcher()
        content = StubContent(title="Anything", body_text="content")
        result = matcher.match(content, [])
        assert result == []


# ===================================================================
# AC-T031-3: keywords (OR logic) and tags (OR logic)
# ===================================================================


class TestMatchRulesOrLogic:
    """Keywords and tags use OR logic for matching."""

    def test_keyword_or_logic_any_keyword_matches(self):
        """Content matching ANY keyword in list should match."""
        from intellisource.distributor.matcher import (
            SubscriptionMatcher,
        )

        matcher = SubscriptionMatcher()
        content = StubContent(
            title="AI News",
            body_text="Machine learning breakthroughs",
        )
        sub = StubSubscription(
            match_rules={
                "keywords": ["AI", "blockchain"],
                "tags": [],
                "min_score": 0,
            }
        )
        result = matcher.match(content, [sub])
        assert len(result) == 1

    def test_keyword_no_match(self):
        """Content matching NONE of the keywords should not match."""
        from intellisource.distributor.matcher import (
            SubscriptionMatcher,
        )

        matcher = SubscriptionMatcher()
        content = StubContent(
            title="Cooking recipes",
            body_text="How to bake a cake",
        )
        sub = StubSubscription(
            match_rules={
                "keywords": ["AI", "blockchain"],
                "tags": [],
                "min_score": 0,
            }
        )
        result = matcher.match(content, [sub])
        assert len(result) == 0

    def test_tag_or_logic_any_tag_matches(self):
        """Content matching ANY tag in the list should match."""
        from intellisource.distributor.matcher import (
            SubscriptionMatcher,
        )

        matcher = SubscriptionMatcher()
        content = StubContent(
            title="Tech update",
            body_text="Latest updates",
            tags=["python", "devops"],
        )
        sub = StubSubscription(
            match_rules={
                "keywords": [],
                "tags": ["python", "rust"],
                "min_score": 0,
            }
        )
        result = matcher.match(content, [sub])
        assert len(result) == 1

    def test_tag_no_match(self):
        """Content with no overlapping tags should not match."""
        from intellisource.distributor.matcher import (
            SubscriptionMatcher,
        )

        matcher = SubscriptionMatcher()
        content = StubContent(
            title="Tech update",
            body_text="Latest updates",
            tags=["java", "spring"],
        )
        sub = StubSubscription(
            match_rules={
                "keywords": [],
                "tags": ["python", "rust"],
                "min_score": 0,
            }
        )
        result = matcher.match(content, [sub])
        assert len(result) == 0

    def test_keyword_and_tag_combined_or(self):
        """Matching either keyword OR tag should suffice."""
        from intellisource.distributor.matcher import (
            SubscriptionMatcher,
        )

        matcher = SubscriptionMatcher()
        # Content has matching tag but no matching keyword
        content = StubContent(
            title="Cooking show",
            body_text="Great recipes",
            tags=["python"],
        )
        sub = StubSubscription(
            match_rules={
                "keywords": ["AI"],
                "tags": ["python"],
                "min_score": 0,
            }
        )
        result = matcher.match(content, [sub])
        assert len(result) == 1

    def test_empty_rules_no_match(self):
        """Subscription with empty keywords and tags matches nothing."""
        from intellisource.distributor.matcher import (
            SubscriptionMatcher,
        )

        matcher = SubscriptionMatcher()
        content = StubContent(title="Anything", body_text="content")
        sub = StubSubscription(
            match_rules={
                "keywords": [],
                "tags": [],
                "min_score": 0,
            }
        )
        result = matcher.match(content, [sub])
        assert len(result) == 0


# ===================================================================
# AC-T031-4: Advanced keyword syntax
# ===================================================================


class TestAdvancedKeywordSyntax:
    """Test +required, !excluded, /regex/ and plain keyword matching."""

    def test_plain_keyword_contains_match(self):
        """Plain keyword: content containing the word matches."""
        from intellisource.distributor.matcher import (
            SubscriptionMatcher,
        )

        matcher = SubscriptionMatcher()
        content = StubContent(
            title="Python tips",
            body_text="Learn Python programming language",
        )
        sub = StubSubscription(
            match_rules={
                "keywords": ["Python"],
                "tags": [],
                "min_score": 0,
            }
        )
        result = matcher.match(content, [sub])
        assert len(result) == 1

    def test_required_keyword_present(self):
        """+keyword: content MUST contain the required keyword."""
        from intellisource.distributor.matcher import (
            SubscriptionMatcher,
        )

        matcher = SubscriptionMatcher()
        content = StubContent(
            title="AI in Python",
            body_text="Using Python for AI development",
        )
        sub = StubSubscription(
            match_rules={
                "keywords": ["+Python", "AI"],
                "tags": [],
                "min_score": 0,
            }
        )
        result = matcher.match(content, [sub])
        assert len(result) == 1

    def test_required_keyword_missing_rejects(self):
        """+keyword missing from content should reject the match."""
        from intellisource.distributor.matcher import (
            SubscriptionMatcher,
        )

        matcher = SubscriptionMatcher()
        content = StubContent(
            title="AI News",
            body_text="Machine learning breakthroughs",
        )
        sub = StubSubscription(
            match_rules={
                "keywords": ["+Python", "AI"],
                "tags": [],
                "min_score": 0,
            }
        )
        result = matcher.match(content, [sub])
        assert len(result) == 0

    def test_excluded_keyword_rejects(self):
        """!keyword: content containing excluded word is rejected."""
        from intellisource.distributor.matcher import (
            SubscriptionMatcher,
        )

        matcher = SubscriptionMatcher()
        content = StubContent(
            title="Python spam tool",
            body_text="Python spam automation",
        )
        sub = StubSubscription(
            match_rules={
                "keywords": ["Python", "!spam"],
                "tags": [],
                "min_score": 0,
            }
        )
        result = matcher.match(content, [sub])
        assert len(result) == 0

    def test_excluded_keyword_absent_allows(self):
        """!keyword absent from content allows match."""
        from intellisource.distributor.matcher import (
            SubscriptionMatcher,
        )

        matcher = SubscriptionMatcher()
        content = StubContent(
            title="Python tips",
            body_text="Clean Python code",
        )
        sub = StubSubscription(
            match_rules={
                "keywords": ["Python", "!spam"],
                "tags": [],
                "min_score": 0,
            }
        )
        result = matcher.match(content, [sub])
        assert len(result) == 1

    def test_regex_keyword_matches(self):
        """/pattern/ regex keyword: content matching regex matches."""
        from intellisource.distributor.matcher import (
            SubscriptionMatcher,
        )

        matcher = SubscriptionMatcher()
        content = StubContent(
            title="CVE-2025-1234 advisory",
            body_text="Security vulnerability CVE-2025-1234",
        )
        sub = StubSubscription(
            match_rules={
                "keywords": ["/CVE-\\d{4}-\\d+/"],
                "tags": [],
                "min_score": 0,
            }
        )
        result = matcher.match(content, [sub])
        assert len(result) == 1

    def test_regex_keyword_no_match(self):
        """/pattern/ regex: content not matching regex is rejected."""
        from intellisource.distributor.matcher import (
            SubscriptionMatcher,
        )

        matcher = SubscriptionMatcher()
        content = StubContent(
            title="General news",
            body_text="Nothing special here",
        )
        sub = StubSubscription(
            match_rules={
                "keywords": ["/CVE-\\d{4}-\\d+/"],
                "tags": [],
                "min_score": 0,
            }
        )
        result = matcher.match(content, [sub])
        assert len(result) == 0

    def test_combined_required_excluded_regex(self):
        """Complex rule: +required, !excluded, /regex/ all applied."""
        from intellisource.distributor.matcher import (
            SubscriptionMatcher,
        )

        matcher = SubscriptionMatcher()
        content = StubContent(
            title="Security update v2.1",
            body_text="Security patch for v2.1.0 release",
        )
        sub = StubSubscription(
            match_rules={
                "keywords": [
                    "+Security",
                    "!malware",
                    "/v\\d+\\.\\d+/",
                ],
                "tags": [],
                "min_score": 0,
            }
        )
        result = matcher.match(content, [sub])
        assert len(result) == 1


# ===================================================================
# AC-043: SubscriptionMatcher pushes matched content to subscriptions
# ===================================================================


class TestSubscriptionMatcherPushIntegration:
    """High-level: matcher routes content to correct subscriptions."""

    def test_multiple_subscriptions_matched(self):
        """Content matching multiple subs returns all of them."""
        from intellisource.distributor.matcher import (
            SubscriptionMatcher,
        )

        matcher = SubscriptionMatcher()
        content = StubContent(
            title="Python AI framework",
            body_text="New Python AI framework released",
            tags=["python", "ai"],
        )
        sub_python = StubSubscription(
            name="python-watcher",
            match_rules={
                "keywords": ["Python"],
                "tags": [],
                "min_score": 0,
            },
        )
        sub_ai = StubSubscription(
            name="ai-watcher",
            match_rules={
                "keywords": [],
                "tags": ["ai"],
                "min_score": 0,
            },
        )
        sub_java = StubSubscription(
            name="java-watcher",
            match_rules={
                "keywords": ["Java"],
                "tags": ["java"],
                "min_score": 0,
            },
        )
        result = matcher.match(content, [sub_python, sub_ai, sub_java])
        matched_names = [s.name for s in result]
        assert "python-watcher" in matched_names
        assert "ai-watcher" in matched_names
        assert "java-watcher" not in matched_names

    def test_inactive_subscription_skipped(self):
        """Paused/inactive subscriptions should be skipped."""
        from intellisource.distributor.matcher import (
            SubscriptionMatcher,
        )

        matcher = SubscriptionMatcher()
        content = StubContent(title="Python news", body_text="Python updates")
        sub = StubSubscription(
            name="paused-sub",
            status="paused",
            match_rules={
                "keywords": ["Python"],
                "tags": [],
                "min_score": 0,
            },
        )
        result = matcher.match(content, [sub])
        assert len(result) == 0


# ===================================================================
# AC-T031-6: min_score threshold filtering (matcher side)
# ===================================================================


class TestMinScoreThresholdInMatcher:
    """Matcher should filter subscriptions by min_score threshold."""

    def test_min_score_zero_no_filtering(self):
        """min_score=0 means no score filtering (all matches pass)."""
        from intellisource.distributor.matcher import (
            SubscriptionMatcher,
        )

        matcher = SubscriptionMatcher()
        content = StubContent(title="Python tips", body_text="Learn Python")
        sub = StubSubscription(
            match_rules={
                "keywords": ["Python"],
                "tags": [],
                "min_score": 0,
            }
        )
        result = matcher.match(content, [sub])
        assert len(result) == 1

    def test_min_score_filters_low_score_content(self):
        """Content below min_score threshold should be excluded."""
        from intellisource.distributor.matcher import (
            SubscriptionMatcher,
        )

        matcher = SubscriptionMatcher()
        # Old content with low credibility -> low score
        content = StubContent(
            title="Python tips",
            body_text="Learn Python",
            source_credibility=0.1,
        )
        sub = StubSubscription(
            match_rules={
                "keywords": ["Python"],
                "tags": [],
                "min_score": 0.8,
            }
        )
        result = matcher.match(content, [sub])
        assert len(result) == 0


# ===================================================================
# AC-T031-7: DeliveryTracker push history and deduplication
# ===================================================================


class TestDeliveryTracker:
    """DeliveryTracker records history and checks for duplicates."""

    def test_import_delivery_tracker(self):
        """DeliveryTracker can be imported."""
        from intellisource.distributor.matcher import (
            DeliveryTracker,
        )

        assert DeliveryTracker is not None

    def test_record_push(self):
        """record() stores a push record."""
        from intellisource.distributor.matcher import (
            DeliveryTracker,
        )

        tracker = DeliveryTracker()
        content_id = uuid.uuid4()
        sub_id = uuid.uuid4()
        tracker.record(content_id=content_id, subscription_id=sub_id)
        assert tracker.has_been_pushed(content_id=content_id, subscription_id=sub_id)

    def test_deduplication_prevents_duplicate_push(self):
        """is_duplicate() returns True for already-pushed combos."""
        from intellisource.distributor.matcher import (
            DeliveryTracker,
        )

        tracker = DeliveryTracker()
        content_id = uuid.uuid4()
        sub_id = uuid.uuid4()
        tracker.record(content_id=content_id, subscription_id=sub_id)
        assert tracker.is_duplicate(content_id=content_id, subscription_id=sub_id)

    def test_not_duplicate_for_new_combination(self):
        """is_duplicate() returns False for new content+sub combo."""
        from intellisource.distributor.matcher import (
            DeliveryTracker,
        )

        tracker = DeliveryTracker()
        assert not tracker.is_duplicate(
            content_id=uuid.uuid4(), subscription_id=uuid.uuid4()
        )

    def test_same_content_different_sub_not_duplicate(self):
        """Same content to different subscription is not duplicate."""
        from intellisource.distributor.matcher import (
            DeliveryTracker,
        )

        tracker = DeliveryTracker()
        content_id = uuid.uuid4()
        sub_id_1 = uuid.uuid4()
        sub_id_2 = uuid.uuid4()
        tracker.record(content_id=content_id, subscription_id=sub_id_1)
        assert not tracker.is_duplicate(content_id=content_id, subscription_id=sub_id_2)
