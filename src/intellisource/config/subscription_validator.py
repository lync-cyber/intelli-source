"""SubscriptionValidator for parsing and validating subscription configuration files."""

from __future__ import annotations

import json
from typing import Any, Final, get_args

import yaml
from pydantic import ValidationError

from intellisource.config.constants import MAX_NAME_LENGTH, RENDER_MODES
from intellisource.config.subscription_models import SubscriptionConfig
from intellisource.config.validator import _resolve_env_vars

_ALLOWED_CHANNELS: Final[frozenset[str]] = frozenset(
    get_args(SubscriptionConfig.model_fields["channel"].annotation)
)
_PATH_TRAVERSAL_CHARS: Final[frozenset[str]] = frozenset({"..", "/", "\\"})
_ALLOWED_WEWORK_MSG_TYPES: Final[frozenset[str]] = frozenset(
    {"text", "markdown", "news"}
)
_ALLOWED_RENDER_MODES: Final[frozenset[str]] = frozenset(RENDER_MODES)


class SubscriptionValidationError(ValueError):
    """Raised when a SubscriptionConfig fails semantic validation."""


def _validate_email_config(channel_config: dict[str, Any]) -> None:
    to_addr = channel_config.get("to_addr", "")
    if not isinstance(to_addr, str) or not to_addr:
        raise SubscriptionValidationError(
            "email channel requires channel_config.to_addr (non-empty string)"
        )
    if "@" not in to_addr:
        raise SubscriptionValidationError(
            f"email channel to_addr {to_addr!r} is not a valid address"
        )


def _validate_wework_config(channel_config: dict[str, Any]) -> None:
    msg_type = channel_config.get("msg_type", "text")
    if msg_type not in _ALLOWED_WEWORK_MSG_TYPES:
        raise SubscriptionValidationError(
            f"wework msg_type {msg_type!r} must be one of "
            f"{sorted(_ALLOWED_WEWORK_MSG_TYPES)}"
        )
    user_id = channel_config.get("user_id", "@all")
    if not isinstance(user_id, str) or not user_id:
        raise SubscriptionValidationError(
            "wework channel_config.user_id must be non-empty string "
            "(use '@all' for broadcast)"
        )


def _validate_wechat_config(channel_config: dict[str, Any]) -> None:
    # WeChat 公众号 has no per-subscription target field; channel_config is
    # essentially empty for v1. Pydantic already enforces dict shape.
    del channel_config  # noqa: F841 - explicit "no checks needed" marker


def _validate_template_config(channel_config: dict[str, Any]) -> None:
    """Validate the optional ``channel_config.template_config`` digest block.

    Channel-independent: only the periodic digest path (daily/weekly) reads it,
    but the keys are validated whenever present so a typo surfaces at reload
    time instead of being silently downgraded to ``code`` at assemble time.
    Template name keeps its runtime fallback and is not checked here.
    """
    tmpl_cfg = channel_config.get("template_config")
    if tmpl_cfg is None:
        return
    if not isinstance(tmpl_cfg, dict):
        raise SubscriptionValidationError(
            "channel_config.template_config must be a mapping"
        )
    mode = tmpl_cfg.get("render_mode")
    if mode is not None and mode not in _ALLOWED_RENDER_MODES:
        raise SubscriptionValidationError(
            f"template_config.render_mode {mode!r} must be one of "
            f"{sorted(_ALLOWED_RENDER_MODES)}"
        )
    budget = tmpl_cfg.get("render_budget_chars")
    if budget is not None and (
        isinstance(budget, bool) or not isinstance(budget, int) or budget <= 0
    ):
        raise SubscriptionValidationError(
            "template_config.render_budget_chars must be a positive integer"
        )


_CHANNEL_VALIDATORS = {
    "email": _validate_email_config,
    "wework": _validate_wework_config,
    "wechat": _validate_wechat_config,
}


class SubscriptionValidator:
    """Validates subscription configuration data."""

    def validate(self, config: SubscriptionConfig) -> SubscriptionConfig:
        """Validate a SubscriptionConfig instance with semantic checks.

        Raises:
            SubscriptionValidationError: If any rule is violated.
        """
        name = config.name
        if not name:
            raise SubscriptionValidationError("name must be non-empty")
        if len(name) > MAX_NAME_LENGTH:
            raise SubscriptionValidationError(
                f"name length {len(name)} exceeds maximum {MAX_NAME_LENGTH}"
            )
        for forbidden in _PATH_TRAVERSAL_CHARS:
            if forbidden in name:
                raise SubscriptionValidationError(
                    f"name contains forbidden character: {forbidden!r}"
                )

        if config.channel not in _ALLOWED_CHANNELS:
            raise SubscriptionValidationError(
                f"channel {config.channel!r} is not one of {sorted(_ALLOWED_CHANNELS)}"
            )

        channel_validator = _CHANNEL_VALIDATORS[config.channel]
        channel_validator(config.channel_config)

        _validate_template_config(config.channel_config)

        return config

    def validate_subscription(self, data: dict[str, Any]) -> SubscriptionConfig:
        """Validate a single subscription configuration dict."""
        return SubscriptionConfig.model_validate(data)

    def validate_subscriptions_file(
        self,
        content: str,
        *,
        format: str,  # noqa: A002
    ) -> list[SubscriptionConfig]:
        """Parse and validate a YAML or JSON subscriptions configuration string.

        Args:
            content: The raw YAML or JSON string.
            format: Either 'yaml' or 'json'.

        Returns:
            A list of validated SubscriptionConfig instances.

        Raises:
            ValueError: If there are validation errors across subscriptions.
            yaml.YAMLError: If YAML syntax is invalid.
            json.JSONDecodeError: If JSON syntax is invalid.
        """
        if format == "yaml":
            parsed = yaml.safe_load(content)
        elif format == "json":
            parsed = json.loads(content)
        else:
            raise ValueError(f"Unsupported format: {format}")

        if not isinstance(parsed, dict):
            raise ValueError(
                "Top-level config must be a mapping with 'subscriptions' key"
            )

        subs_raw: list[Any] = parsed.get("subscriptions", [])
        if not isinstance(subs_raw, list):
            raise ValueError("Expected 'subscriptions' to be a list")

        subs_resolved = _resolve_env_vars(subs_raw)

        results: list[SubscriptionConfig] = []
        errors: list[str] = []
        if not isinstance(subs_resolved, list):
            raise ValueError(
                "Expected 'subscriptions' to be a list after env resolution"
            )

        for i, sub_data in enumerate(subs_resolved):
            try:
                sub = self.validate_subscription(sub_data)
                self.validate(sub)
                results.append(sub)
            except (ValidationError, SubscriptionValidationError) as e:
                errors.append(f"Subscription index {i}: {e}")

        if errors:
            raise ValueError(
                f"Validation failed for {len(errors)} subscription(s):\n"
                + "\n".join(errors)
            )

        return results
