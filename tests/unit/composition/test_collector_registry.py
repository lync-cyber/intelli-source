"""Unit tests for build_collector_registry() — RED phase.

AC-1: composition.build_collector_registry() returns a CollectorRegistry
instance with rss / api / web adapters registered and the returned
instances are of the correct concrete types.
"""

from __future__ import annotations


class TestCollectorRegistryTypes:
    """AC-1: build_collector_registry() registers adapters with correct types."""

    def test_returns_collector_registry_instance(self) -> None:
        """build_collector_registry() returns a CollectorRegistry instance."""
        from intellisource.collector.registry import CollectorRegistry
        from intellisource.composition import build_collector_registry

        registry = build_collector_registry()
        assert isinstance(registry, CollectorRegistry), (
            f"Expected CollectorRegistry, got {type(registry)}"
        )

    def test_rss_collector_is_rss_type(self) -> None:
        """registry.get('rss') returns an instance of RSSCollector."""
        from intellisource.collector.adapters.rss import RSSCollector
        from intellisource.composition import build_collector_registry

        registry = build_collector_registry()
        collector = registry.get("rss")
        assert isinstance(collector, RSSCollector), (
            f"Expected RSSCollector instance for 'rss', got {type(collector)}"
        )

    def test_api_collector_is_api_type(self) -> None:
        """registry.get('api') returns an instance of APICollector."""
        from intellisource.collector.adapters.api import APICollector
        from intellisource.composition import build_collector_registry

        registry = build_collector_registry()
        collector = registry.get("api")
        assert isinstance(collector, APICollector), (
            f"Expected APICollector instance for 'api', got {type(collector)}"
        )

    def test_web_collector_is_web_type(self) -> None:
        """registry.get('web') returns an instance of WebCollector."""
        from intellisource.collector.adapters.web import WebCollector
        from intellisource.composition import build_collector_registry

        registry = build_collector_registry()
        collector = registry.get("web")
        assert isinstance(collector, WebCollector), (
            f"Expected WebCollector instance for 'web', got {type(collector)}"
        )

    def test_unknown_source_type_raises(self) -> None:
        """registry.get('unknown') raises CollectorError (no silent None)."""
        from intellisource.composition import build_collector_registry
        from intellisource.core.errors import CollectorError

        registry = build_collector_registry()
        try:
            registry.get("unknown_type_xyz")
            raise AssertionError(
                "Expected CollectorError for unregistered type, but no exception raised"
            )
        except CollectorError:
            pass

    def test_all_three_types_are_distinct_instances(self) -> None:
        """Each call to registry.get() returns a fresh, distinct instance."""
        from intellisource.composition import build_collector_registry

        registry = build_collector_registry()
        rss1 = registry.get("rss")
        rss2 = registry.get("rss")
        assert rss1 is not rss2, (
            "registry.get('rss') must return a new instance on each call"
        )
