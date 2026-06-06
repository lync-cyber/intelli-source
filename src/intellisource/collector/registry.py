"""CollectorRegistry: registration of source-type collectors."""

from __future__ import annotations

from typing import TYPE_CHECKING

from intellisource.collector.base import BaseCollector
from intellisource.core.errors import CollectorError, ErrorCategory

if TYPE_CHECKING:
    from intellisource.collector.adaptive import AdaptiveScheduler
    from intellisource.collector.proxy import ProxyManager
    from intellisource.collector.rate_limiter import RateLimiter


class CollectorRegistry:
    """Registry for mapping source types to collector classes."""

    def __init__(
        self,
        rate_limiter: RateLimiter | None = None,
        proxy_manager: ProxyManager | None = None,
        adaptive: AdaptiveScheduler | None = None,
    ) -> None:
        self._registry: dict[str, type[BaseCollector]] = {}
        self._rate_limiter = rate_limiter
        self._proxy_manager = proxy_manager
        self._adaptive = adaptive

    def register(self, source_type: str, collector_cls: type[BaseCollector]) -> None:
        """Register a collector class for a given source type.

        Raises TypeError if collector_cls is not a BaseCollector subclass.
        """
        if not (
            isinstance(collector_cls, type) and issubclass(collector_cls, BaseCollector)
        ):
            raise TypeError(f"{collector_cls!r} is not a subclass of BaseCollector")
        self._registry[source_type] = collector_cls

    def get(self, source_type: str) -> BaseCollector:
        """Return an instance of the collector registered for the given type.

        Raises CollectorError with code IS-COL-001 if not found.
        """
        cls = self._registry.get(source_type)
        if cls is None:
            raise CollectorError(
                f"IS-COL-001: No collector registered for type '{source_type}'",
                category=ErrorCategory.UNRECOVERABLE,
            )
        return cls(
            rate_limiter=self._rate_limiter,
            proxy_manager=self._proxy_manager,
            adaptive=self._adaptive,
        )
