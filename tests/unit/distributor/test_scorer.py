"""Tests for ContentScorer weight scoring and push ordering.

Covers:
- AC-043a: SubscriptionMatcher + ContentScorer weight scoring for push
           ordering and threshold filtering
- AC-T031-5: ContentScorer.score(content, subscription) computes weighted
             score = source_credibility * time_decay * keyword_match_score;
             push results ordered by weight descending
- AC-T031-6: min_score threshold filtering via ContentScorer
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

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


# ===================================================================
# AC-T031-5: ContentScorer.score() computes weighted score
# ===================================================================


class TestContentScorerBasic:
    """Verify ContentScorer import and basic scoring interface."""

    def test_import_content_scorer(self):
        """ContentScorer can be imported from distributor.scorer."""
        from intellisource.distributor.scorer import ContentScorer

        assert ContentScorer is not None

    def test_score_returns_float(self):
        """score(content, subscription) should return a float."""
        from intellisource.distributor.scorer import ContentScorer

        scorer = ContentScorer()
        content = StubContent(
            title="Python tips",
            body_text="Learn Python",
            source_credibility=0.9,
        )
        sub = StubSubscription(
            match_rules={
                "keywords": ["Python"],
                "tags": [],
                "min_score": 0,
            }
        )
        result = scorer.score(content, sub)
        assert isinstance(result, float)

    def test_score_is_non_negative(self):
        """Score should always be >= 0."""
        from intellisource.distributor.scorer import ContentScorer

        scorer = ContentScorer()
        content = StubContent(
            title="Random",
            body_text="No keywords here",
            source_credibility=0.5,
        )
        sub = StubSubscription(
            match_rules={
                "keywords": ["Python"],
                "tags": [],
                "min_score": 0,
            }
        )
        result = scorer.score(content, sub)
        assert result >= 0.0


class TestScoringFactors:
    """Verify individual scoring factors affect the result."""

    def test_high_credibility_higher_score(self):
        """Higher source credibility should produce higher score."""
        from intellisource.distributor.scorer import ContentScorer

        scorer = ContentScorer()
        sub = StubSubscription(
            match_rules={
                "keywords": ["Python"],
                "tags": [],
                "min_score": 0,
            }
        )
        content_high = StubContent(
            title="Python tips",
            body_text="Learn Python",
            source_credibility=1.0,
        )
        content_low = StubContent(
            title="Python tips",
            body_text="Learn Python",
            source_credibility=0.2,
            published_at=content_high.published_at,
        )
        score_high = scorer.score(content_high, sub)
        score_low = scorer.score(content_low, sub)
        assert score_high > score_low

    def test_recent_content_higher_score(self):
        """More recent content should score higher (time decay)."""
        from intellisource.distributor.scorer import ContentScorer

        scorer = ContentScorer()
        sub = StubSubscription(
            match_rules={
                "keywords": ["Python"],
                "tags": [],
                "min_score": 0,
            }
        )
        now = datetime.now(tz=timezone.utc)
        content_recent = StubContent(
            title="Python tips",
            body_text="Learn Python",
            source_credibility=1.0,
            published_at=now,
        )
        content_old = StubContent(
            title="Python tips",
            body_text="Learn Python",
            source_credibility=1.0,
            published_at=now - timedelta(days=30),
        )
        score_recent = scorer.score(content_recent, sub)
        score_old = scorer.score(content_old, sub)
        assert score_recent > score_old

    def test_better_keyword_match_higher_score(self):
        """Content with better keyword match should score higher."""
        from intellisource.distributor.scorer import ContentScorer

        scorer = ContentScorer()
        now = datetime.now(tz=timezone.utc)
        sub = StubSubscription(
            match_rules={
                "keywords": ["Python", "tutorial", "advanced"],
                "tags": [],
                "min_score": 0,
            }
        )
        # Content matching all keywords
        content_full = StubContent(
            title="Advanced Python tutorial",
            body_text="Advanced Python tutorial for experts",
            source_credibility=1.0,
            published_at=now,
        )
        # Content matching only one keyword
        content_partial = StubContent(
            title="Python news",
            body_text="General Python news",
            source_credibility=1.0,
            published_at=now,
        )
        score_full = scorer.score(content_full, sub)
        score_partial = scorer.score(content_partial, sub)
        assert score_full > score_partial

    def test_score_formula_multiplicative(self):
        """Score = credibility * time_decay * keyword_match_score."""
        from intellisource.distributor.scorer import ContentScorer

        scorer = ContentScorer()
        now = datetime.now(tz=timezone.utc)
        sub = StubSubscription(
            match_rules={
                "keywords": ["Python"],
                "tags": [],
                "min_score": 0,
            }
        )
        # Zero credibility should yield zero score
        content_zero_cred = StubContent(
            title="Python tips",
            body_text="Learn Python",
            source_credibility=0.0,
            published_at=now,
        )
        score = scorer.score(content_zero_cred, sub)
        assert score == 0.0


# ===================================================================
# AC-043a + AC-T031-5: Push ordering by weight descending
# ===================================================================


class TestPushOrdering:
    """Results should be ordered by score descending."""

    def test_rank_contents_by_score_descending(self):
        """rank() returns contents sorted by score descending."""
        from intellisource.distributor.scorer import ContentScorer

        scorer = ContentScorer()
        now = datetime.now(tz=timezone.utc)
        sub = StubSubscription(
            match_rules={
                "keywords": ["Python"],
                "tags": [],
                "min_score": 0,
            }
        )
        content_a = StubContent(
            title="Python deep dive",
            body_text="Advanced Python programming",
            source_credibility=1.0,
            published_at=now,
        )
        content_b = StubContent(
            title="Python mention",
            body_text="Brief Python mention here",
            source_credibility=0.3,
            published_at=now - timedelta(days=10),
        )
        content_c = StubContent(
            title="Python tutorial",
            body_text="Python for beginners",
            source_credibility=0.7,
            published_at=now - timedelta(days=2),
        )
        ranked = scorer.rank([content_a, content_b, content_c], sub)
        scores = [scorer.score(c, sub) for c in ranked]
        assert scores == sorted(scores, reverse=True)
        assert len(ranked) == 3


# ===================================================================
# AC-T031-6: min_score threshold filtering via scorer
# ===================================================================


class TestMinScoreFiltering:
    """ContentScorer respects min_score threshold for filtering."""

    def test_filter_below_threshold(self):
        """Contents scoring below min_score are excluded."""
        from intellisource.distributor.scorer import ContentScorer

        scorer = ContentScorer()
        now = datetime.now(tz=timezone.utc)
        sub = StubSubscription(
            match_rules={
                "keywords": ["Python"],
                "tags": [],
                "min_score": 0.5,
            }
        )
        content_low = StubContent(
            title="Mention Python",
            body_text="Some text",
            source_credibility=0.1,
            published_at=now - timedelta(days=30),
        )
        content_high = StubContent(
            title="Python deep dive",
            body_text="Python advanced Python tutorial",
            source_credibility=1.0,
            published_at=now,
        )
        filtered = scorer.filter_by_threshold([content_low, content_high], sub)
        assert len(filtered) >= 1
        # Low-score content should be excluded
        filtered_ids = [c.id for c in filtered]
        assert content_low.id not in filtered_ids
        assert content_high.id in filtered_ids

    def test_min_score_zero_passes_all(self):
        """min_score=0 means no filtering, all contents pass."""
        from intellisource.distributor.scorer import ContentScorer

        scorer = ContentScorer()
        now = datetime.now(tz=timezone.utc)
        sub = StubSubscription(
            match_rules={
                "keywords": ["Python"],
                "tags": [],
                "min_score": 0,
            }
        )
        content = StubContent(
            title="Python",
            body_text="Python text",
            source_credibility=0.01,
            published_at=now - timedelta(days=90),
        )
        filtered = scorer.filter_by_threshold([content], sub)
        assert len(filtered) == 1

    def test_filter_and_rank_combined(self):
        """filter + rank: filter by threshold then sort descending."""
        from intellisource.distributor.scorer import ContentScorer

        scorer = ContentScorer()
        now = datetime.now(tz=timezone.utc)
        sub = StubSubscription(
            match_rules={
                "keywords": ["Python"],
                "tags": [],
                "min_score": 0.3,
            }
        )
        contents = [
            StubContent(
                title="Python deep",
                body_text="Python advanced Python",
                source_credibility=1.0,
                published_at=now,
            ),
            StubContent(
                title="Python old",
                body_text="Python ancient text",
                source_credibility=0.05,
                published_at=now - timedelta(days=60),
            ),
            StubContent(
                title="Python mid",
                body_text="Python moderate content",
                source_credibility=0.6,
                published_at=now - timedelta(days=3),
            ),
        ]
        filtered = scorer.filter_by_threshold(contents, sub)
        ranked = scorer.rank(filtered, sub)
        scores = [scorer.score(c, sub) for c in ranked]
        # All should be above threshold
        for s in scores:
            assert s >= 0.3
        # Should be descending
        assert scores == sorted(scores, reverse=True)
