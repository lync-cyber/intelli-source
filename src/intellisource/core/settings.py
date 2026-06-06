"""Centralised application settings sourced from environment variables.

Single source of truth for every ``IS_*`` (and a few unprefixed) environment
variable consumed across the codebase. Fields hold the *raw* string form so
each call site keeps its original parsing/fallback semantics — the Settings
model centralises *where* values come from, not *how* each consumer interprets
them.

Dynamic env access that cannot be modelled as fixed fields stays as direct
``os.environ`` reads: ``${VAR}`` substitution
(:mod:`intellisource.config.validator`), CLI subprocess env merge, and
third-party LLM provider key presence checks.
"""

from __future__ import annotations

import os
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from intellisource.core.encoding import ENCODING
from intellisource.core.paths import resolve_env_file


class Settings(BaseSettings):
    """Environment-backed application configuration."""

    model_config = SettingsConfigDict(
        case_sensitive=False, extra="ignore", env_file_encoding=ENCODING
    )

    # --- Runtime / infra ---
    env: str = Field("", validation_alias="ENV")
    database_url: str | None = Field(None, validation_alias="DATABASE_URL")
    is_database_url: str | None = Field(None, validation_alias="IS_DATABASE_URL")
    redis_url: str | None = Field(None, validation_alias="IS_REDIS_URL")
    celery_broker_url: str | None = Field(None, validation_alias="IS_CELERY_BROKER_URL")
    celery_result_backend: str | None = Field(
        None, validation_alias="IS_CELERY_RESULT_BACKEND"
    )

    # --- API / CLI ---
    api_key: str = Field("", validation_alias="IS_API_KEY")
    api_url: str | None = Field(None, validation_alias="IS_API_URL")

    # --- Logging ---
    log_level: str = Field("INFO", validation_alias="IS_LOG_LEVEL")

    # --- Paths ---
    source_config_dir: str | None = Field(None, validation_alias="IS_SOURCE_CONFIG_DIR")
    subscription_config_dir: str | None = Field(
        None, validation_alias="IS_SUBSCRIPTION_CONFIG_DIR"
    )
    llm_config_path: str | None = Field(None, validation_alias="IS_LLM_CONFIG_PATH")

    # --- SMTP (email channel) ---
    smtp_host: str | None = Field(None, validation_alias="IS_SMTP_HOST")
    smtp_user: str | None = Field(None, validation_alias="IS_SMTP_USER")
    smtp_password: str | None = Field(None, validation_alias="IS_SMTP_PASSWORD")
    smtp_port: str | None = Field(None, validation_alias="IS_SMTP_PORT")
    smtp_use_tls: str = Field("true", validation_alias="IS_SMTP_USE_TLS")

    # --- WeChat Official Account ---
    wechat_app_id: str | None = Field(None, validation_alias="IS_WECHAT_APP_ID")
    wechat_app_secret: str | None = Field(None, validation_alias="IS_WECHAT_APP_SECRET")
    wechat_webhook_token: str = Field("", validation_alias="IS_WECHAT_WEBHOOK_TOKEN")

    # --- WeWork (enterprise WeChat) ---
    wework_corp_id: str | None = Field(None, validation_alias="IS_WEWORK_CORP_ID")
    wework_corp_secret: str | None = Field(
        None, validation_alias="IS_WEWORK_CORP_SECRET"
    )
    wework_agent_id: str | None = Field(None, validation_alias="IS_WEWORK_AGENT_ID")
    wework_webhook_token: str = Field("", validation_alias="IS_WEWORK_WEBHOOK_TOKEN")

    # --- WeCom webhook crypto ---
    wecom_corp_id: str = Field("", validation_alias="IS_WECOM_CORP_ID")
    wecom_token: str = Field("", validation_alias="IS_WECOM_TOKEN")
    wecom_encoding_aes_key: str = Field(
        "", validation_alias="IS_WECOM_ENCODING_AES_KEY"
    )

    # --- Scheduler flags ---
    beat_disabled: str | None = Field(None, validation_alias="IS_BEAT_DISABLED")
    beat_sync_hard_fail: str = Field("", validation_alias="IS_BEAT_SYNC_HARD_FAIL")

    # --- Feature flags ---
    push_optimize_enabled: str | None = Field(
        None, validation_alias="IS_PUSH_OPTIMIZE_ENABLED"
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide cached Settings instance.

    Call ``get_settings.cache_clear()`` to force a re-read of the environment
    (used by tests that mutate env vars between cases).

    ``_env_file`` is resolved per-call so the pytest isolation guard in
    :func:`intellisource.core.paths.resolve_env_file` applies at runtime, not
    at class-definition time.
    """
    return Settings(_env_file=resolve_env_file())


# Provider API keys litellm resolves from ``os.environ`` (no ``IS_`` prefix).
# Authoritative list — startup-warning / doctor checks should reference this
# rather than maintaining their own copies.
PROVIDER_ENV_KEYS = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "DEEPSEEK_API_KEY",
    "AZURE_API_KEY",
    "AZURE_API_BASE",
    "AZURE_API_VERSION",
)


def load_provider_env() -> None:
    """Re-export provider API keys from the ``.env`` file into ``os.environ``.

    litellm reads provider credentials from ``os.environ`` at call time and the
    gateway passes no explicit ``api_key``; pydantic-settings' ``env_file`` only
    populates Settings *fields*, never ``os.environ``. A local bare process
    (uvicorn / celery / CLI) therefore needs this bridge. ``setdefault`` keeps
    any value already present — an explicit export, or Docker's ``env_file:``
    injection (a no-op there). No-op when no env file is resolved (e.g. under
    pytest) or the resolved file is absent.
    """
    env_path = resolve_env_file()
    if env_path is None or not env_path.exists():
        return
    from dotenv import dotenv_values  # noqa: PLC0415

    values = dotenv_values(env_path, encoding=ENCODING)
    for key in PROVIDER_ENV_KEYS:
        val = values.get(key)
        if val:
            os.environ.setdefault(key, val)
