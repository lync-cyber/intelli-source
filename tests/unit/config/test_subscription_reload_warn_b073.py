"""reload 時静默错配 WARN 可观测性测试。

AC1: match_rules 含未知键 → WARN 指明键名与订阅 name；订阅不被拒绝。
AC2: match_rules 无任何有效匹配维度 → WARN 指明"永不匹配"；不拒绝。
AC3: frequency 不在有效集 → WARN 指明非法值与有效集；不拒绝。
AC4: timezone 非法 → WARN；不拒绝。
AC5: 完全合法的订阅 → 不产生任何 WARN。
AC6: WARN 非阻塞，不改变 validate_subscriptions_file 成功/失败语义。
"""

from __future__ import annotations

import pytest
from structlog.testing import capture_logs

from intellisource.config.subscription_validator import SubscriptionValidator

# ---------------------------------------------------------------------------
# Helper: minimal valid YAML subscription
# ---------------------------------------------------------------------------

_VALID_YAML = """
subscriptions:
  - name: "ai-daily"
    channel: "email"
    channel_config:
      to_addr: "user@example.com"
    match_rules:
      keywords:
        - "ai"
    frequency: "daily"
    timezone: "Asia/Shanghai"
"""


def _make_yaml(
    *,
    name: str = "test-sub",
    match_rules: str = 'keywords: ["ai"]',
    frequency: str = "daily",
    timezone: str = "Asia/Shanghai",
) -> str:
    return f"""
subscriptions:
  - name: "{name}"
    channel: "email"
    channel_config:
      to_addr: "user@example.com"
    match_rules:
      {match_rules}
    frequency: "{frequency}"
    timezone: "{timezone}"
"""


def _warn_events(logs: list[dict]) -> list[str]:
    """Return event strings at warning level from capture_logs output."""
    return [str(e.get("event", "")) for e in logs if e.get("log_level") == "warning"]


# ---------------------------------------------------------------------------
# AC1: unknown keys in match_rules → WARN
# ---------------------------------------------------------------------------


class TestAC1UnknownMatchRuleKeys:
    def test_unknown_key_warns_with_key_name_and_sub_name(self) -> None:
        yaml_text = _make_yaml(
            name="sub-typo",
            match_rules='keyowrds: ["ai"]\n      tags: ["x"]',
        )
        with capture_logs() as logs:
            configs = SubscriptionValidator().validate_subscriptions_file(
                yaml_text, format="yaml"
            )

        assert len(configs) == 1, "subscription must not be rejected"
        warns = _warn_events(logs)
        assert any("keyowrds" in m for m in warns), (
            f"WARN must mention unknown key 'keyowrds'; got: {warns}"
        )
        assert any("sub-typo" in m for m in warns), (
            f"WARN must mention subscription name; got: {warns}"
        )

    def test_multiple_unknown_keys_all_warned(self) -> None:
        yaml_text = _make_yaml(
            name="multi-typo",
            match_rules='keyowrds: ["ai"]\n      tgas: ["x"]',
        )
        with capture_logs() as logs:
            configs = SubscriptionValidator().validate_subscriptions_file(
                yaml_text, format="yaml"
            )

        assert len(configs) == 1
        warns = _warn_events(logs)
        # Both unknown keys must appear in at least one warning message
        unknown_covered = any("keyowrds" in m or "tgas" in m for m in warns)
        assert unknown_covered, (
            f"WARN must cover unknown keys 'keyowrds'/'tgas'; got: {warns}"
        )


# ---------------------------------------------------------------------------
# AC2: match_rules without any effective dimension → WARN "never match"
# ---------------------------------------------------------------------------


class TestAC2NeverMatchRules:
    def test_only_min_score_warns_never_match(self) -> None:
        yaml_text = _make_yaml(name="only-score", match_rules="min_score: 5")
        with capture_logs() as logs:
            configs = SubscriptionValidator().validate_subscriptions_file(
                yaml_text, format="yaml"
            )

        assert len(configs) == 1
        warns = _warn_events(logs)
        assert any(
            "never" in m.lower() or "永不" in m or "no effective" in m.lower()
            for m in warns
        ), f"WARN must indicate subscription will never match; got: {warns}"

    def test_explicit_empty_collections_warns_never_match(self) -> None:
        yaml_text = _make_yaml(
            name="empty-collections",
            match_rules="keywords: []\n      tags: []",
        )
        with capture_logs() as logs:
            configs = SubscriptionValidator().validate_subscriptions_file(
                yaml_text, format="yaml"
            )

        assert len(configs) == 1
        warns = _warn_events(logs)
        assert any(
            "never" in m.lower() or "永不" in m or "no effective" in m.lower()
            for m in warns
        ), f"WARN must indicate subscription will never match; got: {warns}"


# ---------------------------------------------------------------------------
# AC3: invalid frequency → WARN with value and valid set
# ---------------------------------------------------------------------------


class TestAC3InvalidFrequency:
    def test_invalid_frequency_warns_with_value_and_valid_set(self) -> None:
        yaml_text = _make_yaml(name="freq-typo", frequency="daly")
        with capture_logs() as logs:
            configs = SubscriptionValidator().validate_subscriptions_file(
                yaml_text, format="yaml"
            )

        assert len(configs) == 1, "subscription must not be rejected"
        warns = _warn_events(logs)
        assert any("daly" in m for m in warns), (
            f"WARN must mention invalid frequency value; got: {warns}"
        )
        assert any(
            "daily" in m or "weekly" in m or "realtime" in m or "hourly" in m
            for m in warns
        ), f"WARN must hint at valid values; got: {warns}"

    def test_empty_string_frequency_warns(self) -> None:
        yaml_text = _make_yaml(name="freq-empty", frequency="")
        with capture_logs() as logs:
            configs = SubscriptionValidator().validate_subscriptions_file(
                yaml_text, format="yaml"
            )

        assert len(configs) == 1
        warns = _warn_events(logs)
        assert any("frequency" in m.lower() for m in warns), (
            f"WARN must mention frequency; got: {warns}"
        )


# ---------------------------------------------------------------------------
# AC4: invalid timezone → WARN; subscription not rejected
# ---------------------------------------------------------------------------


class TestAC4InvalidTimezone:
    def test_invalid_timezone_warns(self) -> None:
        yaml_text = _make_yaml(name="tz-bad", timezone="Mars/Phobos")
        with capture_logs() as logs:
            configs = SubscriptionValidator().validate_subscriptions_file(
                yaml_text, format="yaml"
            )

        assert len(configs) == 1, "subscription must not be rejected"
        warns = _warn_events(logs)
        assert any("Mars/Phobos" in m or "timezone" in m.lower() for m in warns), (
            f"WARN must mention invalid timezone; got: {warns}"
        )

    def test_garbage_timezone_warns(self) -> None:
        yaml_text = _make_yaml(name="tz-garbage", timezone="NotATimezone")
        with capture_logs() as logs:
            configs = SubscriptionValidator().validate_subscriptions_file(
                yaml_text, format="yaml"
            )

        assert len(configs) == 1
        warns = _warn_events(logs)
        assert any("timezone" in m.lower() or "NotATimezone" in m for m in warns)


# ---------------------------------------------------------------------------
# AC5: fully valid subscription → no WARN
# ---------------------------------------------------------------------------


class TestAC5NoWarnOnValidSubscription:
    def test_valid_subscription_produces_no_warn(self) -> None:
        with capture_logs() as logs:
            configs = SubscriptionValidator().validate_subscriptions_file(
                _VALID_YAML, format="yaml"
            )

        assert len(configs) == 1
        warns = _warn_events(logs)
        assert warns == [], f"No WARN expected for valid subscription; got: {warns}"

    def test_valid_wework_subscription_produces_no_warn(self) -> None:
        yaml_text = """
subscriptions:
  - name: "wework-ok"
    channel: "wework"
    channel_config:
      user_id: "@all"
    match_rules:
      tags:
        - "tech"
    frequency: "realtime"
    timezone: "UTC"
"""
        with capture_logs() as logs:
            configs = SubscriptionValidator().validate_subscriptions_file(
                yaml_text, format="yaml"
            )

        assert len(configs) == 1
        warns = _warn_events(logs)
        assert warns == [], f"No WARN expected; got: {warns}"


# ---------------------------------------------------------------------------
# AC6: WARNs are non-blocking — success/failure semantics unchanged
# ---------------------------------------------------------------------------


class TestAC6NonBlocking:
    def test_misconfig_warn_does_not_raise(self) -> None:
        """Subscriptions with silent misconfigs must still be returned, not raised."""
        yaml_text = _make_yaml(
            name="misconfig",
            match_rules='keyowrds: ["ai"]',
            frequency="daly",
            timezone="Mars/Phobos",
        )
        # Must not raise
        configs = SubscriptionValidator().validate_subscriptions_file(
            yaml_text, format="yaml"
        )
        assert len(configs) == 1

    def test_one_invalid_one_warn_still_raises_for_invalid(self) -> None:
        """A hard-invalid subscription (missing to_addr) still raises ValueError
        even when another subscription only has soft misconfigs."""
        yaml_text = """
subscriptions:
  - name: "soft-warn"
    channel: "email"
    channel_config:
      to_addr: "user@example.com"
    match_rules:
      keyowrds:
        - "ai"
    frequency: "daly"
    timezone: "Mars/Phobos"
  - name: "hard-invalid"
    channel: "email"
    channel_config: {}
    match_rules:
      keywords:
        - "tech"
"""
        with pytest.raises(ValueError, match="Validation failed for 1 subscription"):
            SubscriptionValidator().validate_subscriptions_file(
                yaml_text, format="yaml"
            )
