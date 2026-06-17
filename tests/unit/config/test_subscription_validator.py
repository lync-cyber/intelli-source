"""Tests for SubscriptionValidator (Phase 1)."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from intellisource.config.subscription_models import SubscriptionConfig
from intellisource.config.subscription_validator import (
    SubscriptionValidationError,
    SubscriptionValidator,
)

# ---------------------------------------------------------------------------
# Per-channel validate() rules
# ---------------------------------------------------------------------------


class TestEmailChannelValidation:
    def test_email_with_valid_to_addr_passes(self) -> None:
        cfg = SubscriptionConfig(
            name="test", channel="email", channel_config={"to_addr": "u@example.com"}
        )
        result = SubscriptionValidator().validate(cfg)
        assert result is cfg

    def test_email_missing_to_addr_fails(self) -> None:
        cfg = SubscriptionConfig(name="test", channel="email", channel_config={})
        with pytest.raises(SubscriptionValidationError, match="to_addr"):
            SubscriptionValidator().validate(cfg)

    def test_email_empty_to_addr_fails(self) -> None:
        cfg = SubscriptionConfig(
            name="test", channel="email", channel_config={"to_addr": ""}
        )
        with pytest.raises(SubscriptionValidationError, match="to_addr"):
            SubscriptionValidator().validate(cfg)

    def test_email_to_addr_without_at_fails(self) -> None:
        cfg = SubscriptionConfig(
            name="test", channel="email", channel_config={"to_addr": "not-an-email"}
        )
        with pytest.raises(SubscriptionValidationError, match="not a valid address"):
            SubscriptionValidator().validate(cfg)


class TestWeWorkChannelValidation:
    def test_wework_defaults_pass(self) -> None:
        cfg = SubscriptionConfig(name="test", channel="wework", channel_config={})
        # defaults: user_id=@all, msg_type=text — should pass when explicit
        cfg2 = SubscriptionConfig(
            name="test",
            channel="wework",
            channel_config={"user_id": "@all", "msg_type": "text"},
        )
        SubscriptionValidator().validate(cfg2)
        # empty channel_config also passes because we read defaults via .get()
        SubscriptionValidator().validate(cfg)

    def test_wework_markdown_msg_type_passes(self) -> None:
        cfg = SubscriptionConfig(
            name="test",
            channel="wework",
            channel_config={"user_id": "ZhangSan", "msg_type": "markdown"},
        )
        SubscriptionValidator().validate(cfg)

    def test_wework_invalid_msg_type_fails(self) -> None:
        cfg = SubscriptionConfig(
            name="test",
            channel="wework",
            channel_config={"user_id": "Z", "msg_type": "image"},
        )
        with pytest.raises(SubscriptionValidationError, match="msg_type"):
            SubscriptionValidator().validate(cfg)

    def test_wework_empty_user_id_fails(self) -> None:
        cfg = SubscriptionConfig(
            name="test", channel="wework", channel_config={"user_id": ""}
        )
        with pytest.raises(SubscriptionValidationError, match="user_id"):
            SubscriptionValidator().validate(cfg)

    def test_wework_pipe_separated_user_ids_passes(self) -> None:
        cfg = SubscriptionConfig(
            name="test",
            channel="wework",
            channel_config={"user_id": "ZhangSan|LiSi|WangWu"},
        )
        SubscriptionValidator().validate(cfg)


class TestWeChatChannelValidation:
    def test_wechat_empty_channel_config_passes(self) -> None:
        cfg = SubscriptionConfig(name="test", channel="wechat", channel_config={})
        SubscriptionValidator().validate(cfg)

    def test_wechat_any_channel_config_passes(self) -> None:
        cfg = SubscriptionConfig(
            name="test",
            channel="wechat",
            channel_config={"arbitrary": "field", "v": 42},
        )
        SubscriptionValidator().validate(cfg)


# ---------------------------------------------------------------------------
# template_config (digest render policy) validation
# ---------------------------------------------------------------------------


class TestTemplateConfigValidation:
    def _email(self, template_config: dict[str, object]) -> SubscriptionConfig:
        return SubscriptionConfig(
            name="digest",
            channel="email",
            channel_config={"to_addr": "u@x.com", "template_config": template_config},
        )

    def test_valid_render_mode_passes_through(self) -> None:
        cfg = self._email({"render_mode": "llm-freeform"})
        out = SubscriptionValidator().validate(cfg)
        assert out.channel_config["template_config"]["render_mode"] == "llm-freeform"

    def test_invalid_render_mode_rejected(self) -> None:
        # underscore typo is the realistic mistake; must surface, not silently
        # downgrade to "code" at assemble time.
        with pytest.raises(SubscriptionValidationError, match="render_mode"):
            SubscriptionValidator().validate(
                self._email({"render_mode": "llm_freeform"})
            )

    def test_nonpositive_budget_rejected(self) -> None:
        with pytest.raises(SubscriptionValidationError, match="render_budget_chars"):
            SubscriptionValidator().validate(self._email({"render_budget_chars": 0}))

    def test_bool_budget_rejected(self) -> None:
        with pytest.raises(SubscriptionValidationError, match="render_budget_chars"):
            SubscriptionValidator().validate(self._email({"render_budget_chars": True}))

    def test_positive_budget_passes(self) -> None:
        cfg = self._email({"render_mode": "llm-freeform", "render_budget_chars": 4000})
        out = SubscriptionValidator().validate(cfg)
        assert out.channel_config["template_config"]["render_budget_chars"] == 4000

    def test_non_mapping_template_config_rejected(self) -> None:
        cfg = SubscriptionConfig(
            name="digest",
            channel="email",
            channel_config={"to_addr": "u@x.com", "template_config": "oops"},
        )
        with pytest.raises(SubscriptionValidationError, match="template_config"):
            SubscriptionValidator().validate(cfg)

    def test_absent_template_config_passes(self) -> None:
        cfg = SubscriptionConfig(
            name="digest", channel="email", channel_config={"to_addr": "u@x.com"}
        )
        out = SubscriptionValidator().validate(cfg)
        assert out.channel == "email"


# ---------------------------------------------------------------------------
# Name validation
# ---------------------------------------------------------------------------


class TestNameValidation:
    def _email_cfg(self, name: str) -> SubscriptionConfig:
        return SubscriptionConfig(
            name=name, channel="email", channel_config={"to_addr": "u@x.com"}
        )

    def test_empty_name_fails(self) -> None:
        with pytest.raises(SubscriptionValidationError, match="non-empty"):
            SubscriptionValidator().validate(self._email_cfg(""))

    def test_too_long_name_fails(self) -> None:
        with pytest.raises(SubscriptionValidationError, match="exceeds maximum"):
            SubscriptionValidator().validate(self._email_cfg("x" * 101))

    def test_name_with_path_traversal_dot_dot_fails(self) -> None:
        with pytest.raises(SubscriptionValidationError, match="forbidden character"):
            SubscriptionValidator().validate(self._email_cfg("evil..name"))

    def test_name_with_slash_fails(self) -> None:
        with pytest.raises(SubscriptionValidationError, match="forbidden character"):
            SubscriptionValidator().validate(self._email_cfg("evil/name"))


# ---------------------------------------------------------------------------
# validate_subscriptions_file YAML/JSON parsing
# ---------------------------------------------------------------------------


class TestParseSubscriptionsFile:
    def test_valid_yaml_with_three_channels_parses(self) -> None:
        yaml_text = """
subscriptions:
  - name: "AI Digest"
    channel: "wework"
    channel_config:
      user_id: "@all"
      msg_type: "markdown"
    match_rules:
      tags: ["ai"]
  - name: "Tech Email"
    channel: "email"
    channel_config:
      to_addr: "user@example.com"
    match_rules:
      tags: ["tech"]
  - name: "Security Alert"
    channel: "wechat"
    channel_config: {}
    match_rules:
      tags: ["security"]
"""
        configs = SubscriptionValidator().validate_subscriptions_file(
            yaml_text, format="yaml"
        )
        assert len(configs) == 3
        assert configs[0].name == "AI Digest"
        assert configs[0].channel == "wework"
        assert configs[1].channel == "email"
        assert configs[1].channel_config["to_addr"] == "user@example.com"

    def test_env_var_resolution_in_channel_config(self) -> None:
        yaml_text = """
subscriptions:
  - name: "Env Test"
    channel: "email"
    channel_config:
      to_addr: "${IS_DIGEST_TEST_EMAIL}"
    match_rules: {}
"""
        with patch.dict(os.environ, {"IS_DIGEST_TEST_EMAIL": "resolved@example.com"}):
            configs = SubscriptionValidator().validate_subscriptions_file(
                yaml_text, format="yaml"
            )
        assert configs[0].channel_config["to_addr"] == "resolved@example.com"

    def test_one_invalid_aggregates_into_error_message(self) -> None:
        yaml_text = """
subscriptions:
  - name: "Valid"
    channel: "email"
    channel_config: {"to_addr": "ok@x.com"}
    match_rules: {}
  - name: "Bad"
    channel: "email"
    channel_config: {}
    match_rules: {}
"""
        with pytest.raises(ValueError, match="Validation failed for 1 subscription"):
            SubscriptionValidator().validate_subscriptions_file(
                yaml_text, format="yaml"
            )

    def test_missing_subscriptions_key_returns_empty(self) -> None:
        yaml_text = "sources:\n  - name: foo"  # wrong top-level key
        configs = SubscriptionValidator().validate_subscriptions_file(
            yaml_text, format="yaml"
        )
        assert configs == []

    def test_subscriptions_not_a_list_raises(self) -> None:
        yaml_text = "subscriptions: not-a-list"
        with pytest.raises(ValueError, match="subscriptions.*list"):
            SubscriptionValidator().validate_subscriptions_file(
                yaml_text, format="yaml"
            )

    def test_unsupported_format_raises(self) -> None:
        with pytest.raises(ValueError, match="Unsupported format"):
            SubscriptionValidator().validate_subscriptions_file("{}", format="xml")

    def test_json_format_parses(self) -> None:
        json_text = (
            '{"subscriptions":[{"name":"j","channel":"wework",'
            '"channel_config":{"user_id":"@all","msg_type":"text"},'
            '"match_rules":{"tags":["x"]}}]}'
        )
        configs = SubscriptionValidator().validate_subscriptions_file(
            json_text, format="json"
        )
        assert len(configs) == 1
        assert configs[0].name == "j"
