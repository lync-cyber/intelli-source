"""Centralised application settings sourced from environment variables.

Single source of truth for every ``IS_*`` (and a few unprefixed) environment
variable consumed across the codebase. Fields hold the *raw* string form so
each call site keeps its original parsing/fallback semantics — the Settings
model centralises *where* values come from, not *how* each consumer interprets
them.

Dynamic env access that cannot be modelled as fixed fields stays as direct
``os.environ`` reads: prefix-scanning config overrides
(:mod:`intellisource.config.resolver`), ``${VAR}`` substitution
(:mod:`intellisource.config.validator`), CLI subprocess env merge, and
third-party LLM provider key presence checks.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed application configuration."""

    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")

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
    """
    return Settings()
