"""Proxy management for collector sources."""

from __future__ import annotations


class ProxyManager:
    """Routes proxy addresses by source_id based on configuration."""

    def __init__(self, config: dict[str, str]) -> None:
        self._config = config

    def get_proxy(self, source_id: str) -> str | None:
        """Return the proxy URL for *source_id*, or None if not configured."""
        return self._config.get(source_id)
