"""Subscription configuration loading and DB sync."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from intellisource.config.loader import ConfigPathError, _detect_format
from intellisource.config.subscription_models import SubscriptionConfig
from intellisource.config.subscription_validator import SubscriptionValidator
from intellisource.core.settings import get_settings
from intellisource.observability.logging import get_logger

logger = get_logger(__name__)


class SubscriptionConfigLoader:
    """Loads subscription configuration files and syncs them to the database."""

    def __init__(self) -> None:
        self._validator = SubscriptionValidator()
        config_dir_env = get_settings().subscription_config_dir
        self._config_dir: Path | None = Path(config_dir_env) if config_dir_env else None

    def load_file(self, file_path: str) -> list[SubscriptionConfig]:
        """Load and validate a subscription configuration file (YAML or JSON).

        Raises ConfigPathError if the resolved path escapes the config directory.
        """
        resolved = Path(file_path).resolve()

        if self._config_dir is not None:
            allowed_dir = self._config_dir.resolve()
            try:
                resolved.relative_to(allowed_dir)
            except ValueError:
                raise ConfigPathError(
                    f"path {file_path!r} escapes subscription config directory "
                    f"{str(allowed_dir)!r}"
                )

        fmt = _detect_format(file_path)
        with open(resolved, encoding="utf-8") as f:
            content = f.read()

        return self._validator.validate_subscriptions_file(content, format=fmt)

    def load_subscription_configs(self) -> list[SubscriptionConfig]:
        """Scan the configured directory and load all *.yaml / *.yml config files.

        Returns an empty list when IS_SUBSCRIPTION_CONFIG_DIR is unset or absent.
        """
        if self._config_dir is None:
            logger.warning(
                "IS_SUBSCRIPTION_CONFIG_DIR is not set; "
                "skipping subscription config scan"
            )
            return []

        config_dir = self._config_dir.resolve()
        if not config_dir.is_dir():
            logger.warning(
                "Subscription config directory %s does not exist; skipping scan",
                config_dir,
            )
            return []

        results: list[SubscriptionConfig] = []
        for pattern in ("*.yaml", "*.yml"):
            for config_path in sorted(config_dir.glob(pattern)):
                try:
                    loaded = self.load_file(str(config_path))
                    results.extend(loaded)
                except Exception:
                    logger.exception(
                        "Failed to load subscription config file %s", config_path
                    )

        return results

    async def sync_to_db(
        self,
        configs: Sequence[SubscriptionConfig],
        session: AsyncSession,
    ) -> None:
        """Sync subscription configs to the database via bulk_sync_from_configs."""
        from intellisource.storage.repositories.subscription import (
            SubscriptionRepository,
        )

        repo = SubscriptionRepository(session)
        await repo.bulk_sync_from_configs(list(configs))
