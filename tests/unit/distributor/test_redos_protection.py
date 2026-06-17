"""Tests for ReDoS protection in keyword matching (AC-5).

security_sensitive=true:
- /regex/ branch must use `regex.search(pattern, text, timeout=1.0)` (third-party
  `regex` library), NOT `re.search`.
- TimeoutError (built-in, raised by regex.search when timeout= triggers)
  is caught; keyword returns False.
- Catastrophic backtracking patterns must not block for > 2 seconds.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Stub helpers
# ---------------------------------------------------------------------------


@dataclass
class StubSubscription:
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    match_rules: dict = field(
        default_factory=lambda: {"keywords": [], "tags": [], "min_score": 0}
    )
    status: str = "active"


@dataclass
class StubContent:
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    title: str = ""
    body_text: str = ""
    tags: list[str] = field(default_factory=list)
    source_credibility: float = 1.0
    published_at: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REDOS_PATTERNS = [
    "(a+)+$",  # classic catastrophic backtracking
    "^(a+)+$",  # anchored variant
    "(.*)*",  # nested star
    "(a|a)+",  # alternation overlap
]

_TRIGGER_STRING = "a" * 30 + "b"  # no match → forces max backtracking


# ===========================================================================
# AC-5: regex library usage and timeout protection
# ===========================================================================


class TestReDoSProtectionKeywordMatches:
    """keyword_matches / _evaluate_keywords must use regex library with timeout."""

    def _evaluate(self, pattern_kw: str, text: str) -> bool | None:
        """Call SubscriptionMatcher._evaluate_keywords with a single /regex/ keyword."""
        from intellisource.distributor.matcher import SubscriptionMatcher

        matcher = SubscriptionMatcher()
        return matcher._evaluate_keywords([pattern_kw], text, text.lower())

    def test_redos_pattern_does_not_block_beyond_2s(self):
        """AC-5: catastrophic backtracking pattern with long input completes < 2s."""
        from intellisource.distributor.matcher import SubscriptionMatcher

        matcher = SubscriptionMatcher()
        kw = "/(a+)+$/"
        text = _TRIGGER_STRING

        t0 = time.monotonic()
        result = matcher._evaluate_keywords([kw], text, text.lower())
        elapsed = time.monotonic() - t0

        assert elapsed < 2.0, (
            f"ReDoS pattern '(a+)+$' blocked for {elapsed:.2f}s "
            "(expected < 2.0s with regex timeout=1.0)"
        )
        # Result must be False (no match, not None which signals constraint violation)
        assert result is False

    @pytest.mark.parametrize("pattern", _REDOS_PATTERNS)
    def test_all_redos_patterns_complete_quickly(self, pattern: str):
        """AC-5: all known catastrophic patterns with trigger string complete < 2s."""
        from intellisource.distributor.matcher import SubscriptionMatcher

        matcher = SubscriptionMatcher()
        kw = f"/{pattern}/"

        t0 = time.monotonic()
        matcher._evaluate_keywords([kw], _TRIGGER_STRING, _TRIGGER_STRING.lower())
        elapsed = time.monotonic() - t0

        assert elapsed < 2.0, (
            f"Pattern /{pattern}/ blocked for {elapsed:.2f}s "
            "(timeout protection failed)"
        )

    def test_regex_timeout_error_captured_returns_false(self):
        """AC-5: regex.TimeoutError is caught; keyword returns False (no match signal).

        Verifies that the implementation catches regex.TimeoutError specifically
        and returns False for that keyword rather than propagating the exception.
        """
        import regex as regex_lib  # third-party; must be importable

        # Inject a mock that raises TimeoutError to confirm the catch path
        with patch.object(
            regex_lib,
            "search",
            side_effect=TimeoutError("timeout"),
        ) as mock_search:
            from intellisource.distributor.matcher import SubscriptionMatcher

            matcher = SubscriptionMatcher()
            result = matcher._evaluate_keywords(["/py.*/"], "python", "python")

        mock_search.assert_called_once()
        # TimeoutError caught → keyword is treated as no-match → result is False
        assert result is False

    def test_regex_library_is_used_not_re(self):
        """AC-5: /regex/ branch calls regex.search (third-party) not re.search."""
        import regex as regex_lib

        call_args_list = []
        original_search = regex_lib.search

        def spy_search(pattern, string, *args, **kwargs):
            call_args_list.append((pattern, string, args, kwargs))
            return original_search(pattern, string, *args, **kwargs)

        with patch.object(regex_lib, "search", side_effect=spy_search):
            from intellisource.distributor.matcher import SubscriptionMatcher

            matcher = SubscriptionMatcher()
            matcher._evaluate_keywords(["/py.*/"], "python guide", "python guide")

        assert len(call_args_list) >= 1, (
            "regex.search was not called; implementation may still use re.search"
        )

    def test_regex_search_called_with_timeout_kwarg(self):
        """AC-5: regex.search is called with timeout=1.0 keyword argument."""
        import regex as regex_lib

        captured_kwargs: list[dict] = []

        def spy_search(pattern, string, *args, **kwargs):
            captured_kwargs.append(kwargs)
            return None  # simulate no match

        with patch.object(regex_lib, "search", side_effect=spy_search):
            from intellisource.distributor.matcher import SubscriptionMatcher

            matcher = SubscriptionMatcher()
            matcher._evaluate_keywords(["/py.*/"], "python guide", "python guide")

        assert len(captured_kwargs) >= 1, "regex.search was not invoked"
        assert "timeout" in captured_kwargs[0], (
            f"regex.search not called with timeout kwarg; "
            f"got kwargs={captured_kwargs[0]}"
        )
        assert captured_kwargs[0]["timeout"] == pytest.approx(1.0), (
            f"Expected timeout=1.0, got {captured_kwargs[0]['timeout']}"
        )

    def test_normal_regex_pattern_still_matches(self):
        """AC-5: non-catastrophic /regex/ still works correctly after protection."""
        from intellisource.distributor.matcher import SubscriptionMatcher

        matcher = SubscriptionMatcher()
        result = matcher._evaluate_keywords(
            ["/py.*/"], "python programming", "python programming"
        )
        assert result is True

    def test_timeout_logged_not_silently_swallowed(self):
        """AC-5: TimeoutError from regex.search timeout must be logged."""
        import regex as regex_lib
        from structlog.testing import capture_logs

        with patch.object(
            regex_lib,
            "search",
            side_effect=TimeoutError("mock timeout"),
        ):
            from intellisource.distributor.matcher import SubscriptionMatcher

            with capture_logs() as logs:
                matcher = SubscriptionMatcher()
                matcher._evaluate_keywords(["/py.*/"], "python", "python")

        assert len(logs) >= 1, (
            "regex.TimeoutError was not logged; silent swallowing is not allowed"
        )

    def test_timeout_log_does_not_leak_pattern(self):
        """AC-5: timeout warning must not contain the raw pattern text."""
        import regex as regex_lib
        from structlog.testing import capture_logs

        pattern = "(secret_business_keyword_xyz+)+$"
        kw = f"/{pattern}/"

        with patch.object(
            regex_lib,
            "search",
            side_effect=TimeoutError("mock timeout"),
        ):
            from intellisource.distributor.matcher import SubscriptionMatcher

            with capture_logs() as logs:
                matcher = SubscriptionMatcher()
                matcher._evaluate_keywords([kw], "some text", "some text")

        events = " ".join(e["event"] for e in logs)
        assert pattern not in events, (
            "Timeout log must not contain the raw pattern string"
        )
        assert "sha256=" in events, (
            "Timeout log should include sha256= hash for traceability"
        )
