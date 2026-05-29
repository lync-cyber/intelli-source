"""Tests for CollectorRegistry: manual registration and auto-discovery.

Covers:
- AC-T010-1: CollectorRegistry.register(type, collector_cls) registers a collector
- AC-T010-2: CollectorRegistry.get(type) returns the correct collector instance
- AC-T010-3: Unregistered type raises CollectorError (IS-COL-001)
- AC-T010-5: Auto-discovery scans collector/sources/ and registers BaseCollector subs
- AC-T010-6: New sources/ sub-packages need only to implement BaseCollector + export
  in __init__.py
"""

from __future__ import annotations

import pytest

from intellisource.collector.base import BaseCollector, RawContent
from intellisource.collector.registry import CollectorRegistry
from intellisource.core.errors import CollectorError, ErrorCategory

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeRSSCollector(BaseCollector):
    """Stub collector for 'rss' source type."""

    async def collect(self, source_config: dict) -> list[RawContent]:
        return [
            RawContent(
                title="RSS Item",
                source_url="https://example.com/rss/1",
                fingerprint="a" * 64,
            )
        ]


class _FakeWebCollector(BaseCollector):
    """Stub collector for 'web' source type."""

    async def collect(self, source_config: dict) -> list[RawContent]:
        return []


class _NotACollector:
    """Plain class that does NOT inherit BaseCollector."""

    pass


# ===================================================================
# AC-T010-1: register(type, collector_cls)
# ===================================================================


class TestCollectorRegistryRegister:
    """Verify manual registration of collector classes."""

    def test_register_valid_collector(self):
        """register() accepts a BaseCollector subclass without error."""
        registry = CollectorRegistry()
        registry.register("rss", _FakeRSSCollector)
        # If we get here without exception, registration succeeded.
        # We verify via get() in the next test class, but also do a
        # basic assertion that the registry is not empty.
        assert isinstance(registry.get("rss"), BaseCollector)

    def test_register_multiple_types(self):
        """Different source types can be registered independently."""
        registry = CollectorRegistry()
        registry.register("rss", _FakeRSSCollector)
        registry.register("web", _FakeWebCollector)
        assert isinstance(registry.get("rss"), BaseCollector)
        assert isinstance(registry.get("web"), BaseCollector)

    def test_register_overwrites_existing(self):
        """Registering the same type twice replaces the previous entry."""
        registry = CollectorRegistry()
        registry.register("rss", _FakeRSSCollector)
        registry.register("rss", _FakeWebCollector)
        instance = registry.get("rss")
        assert isinstance(instance, _FakeWebCollector)

    def test_register_rejects_non_basecollector(self):
        """register() should reject classes that do not extend BaseCollector."""
        registry = CollectorRegistry()
        with pytest.raises((TypeError, ValueError)):
            registry.register("bad", _NotACollector)  # type: ignore[arg-type]


# ===================================================================
# AC-T010-2: get(type) returns corresponding collector instance
# ===================================================================


class TestCollectorRegistryGet:
    """Verify get() returns the correct collector instance by source type."""

    def test_get_returns_instance_of_registered_class(self):
        """get() returns an instance (not the class itself) of the
        registered collector."""
        registry = CollectorRegistry()
        registry.register("rss", _FakeRSSCollector)
        instance = registry.get("rss")
        assert isinstance(instance, _FakeRSSCollector)

    def test_get_returns_correct_type_for_each_registration(self):
        """get() distinguishes between different registered types."""
        registry = CollectorRegistry()
        registry.register("rss", _FakeRSSCollector)
        registry.register("web", _FakeWebCollector)
        assert isinstance(registry.get("rss"), _FakeRSSCollector)
        assert isinstance(registry.get("web"), _FakeWebCollector)


# ===================================================================
# AC-T010-3: Unregistered type raises CollectorError (IS-COL-001)
# ===================================================================


class TestCollectorRegistryUnregisteredType:
    """Verify that requesting an unregistered type raises a clear error."""

    def test_get_unregistered_type_raises_collector_error(self):
        """get() with an unknown type must raise CollectorError."""
        registry = CollectorRegistry()
        with pytest.raises(CollectorError) as exc_info:
            registry.get("nonexistent")
        assert "IS-COL-001" in str(exc_info.value)

    def test_get_unregistered_type_error_category(self):
        """The error for unregistered type should have UNRECOVERABLE category,
        since it indicates a configuration/programming error rather than
        a transient issue."""
        registry = CollectorRegistry()
        with pytest.raises(CollectorError) as exc_info:
            registry.get("nonexistent")
        assert exc_info.value.category == ErrorCategory.UNRECOVERABLE

    def test_get_empty_registry_raises(self):
        """get() on an empty registry also raises CollectorError."""
        registry = CollectorRegistry()
        with pytest.raises(CollectorError):
            registry.get("rss")


# ===================================================================
# AC-T010-5: Auto-discovery scans collector/sources/ directory
# ===================================================================


class TestCollectorRegistryAutoDiscover:
    """Verify auto-discovery loads BaseCollector subclasses from
    collector/sources/ sub-packages."""

    def test_auto_discover_registers_found_collectors(self, tmp_path):
        """auto_discover() scans the sources directory and registers
        all BaseCollector subclasses found in sub-package __init__.py."""
        registry = CollectorRegistry()

        # Create a fake sources package with a sub-package that exports
        # a BaseCollector subclass.
        sources_dir = tmp_path / "sources"
        sources_dir.mkdir()
        (sources_dir / "__init__.py").write_text("")
        rss_dir = sources_dir / "rss"
        rss_dir.mkdir()
        (rss_dir / "__init__.py").write_text(
            "from intellisource.collector.base import BaseCollector, RawContent\n"
            "class RSSCollector(BaseCollector):\n"
            "    SOURCE_TYPE = 'rss'\n"
            "    async def collect(self, source_config):\n"
            "        return []\n"
        )

        registry.auto_discover(str(sources_dir))

        instance = registry.get("rss")
        assert isinstance(instance, BaseCollector)

    def test_auto_discover_ignores_non_collector_classes(self, tmp_path):
        """auto_discover() skips classes that don't extend BaseCollector."""
        registry = CollectorRegistry()

        sources_dir = tmp_path / "sources"
        sources_dir.mkdir()
        (sources_dir / "__init__.py").write_text("")
        helper_dir = sources_dir / "helpers"
        helper_dir.mkdir()
        (helper_dir / "__init__.py").write_text(
            "class NotACollector:\n    SOURCE_TYPE = 'fake'\n    pass\n"
        )

        registry.auto_discover(str(sources_dir))

        with pytest.raises(CollectorError):
            registry.get("fake")

    def test_auto_discover_multiple_sources(self, tmp_path):
        """auto_discover() registers multiple collector sub-packages."""
        registry = CollectorRegistry()

        sources_dir = tmp_path / "sources"
        sources_dir.mkdir()
        (sources_dir / "__init__.py").write_text("")

        for name in ("rss", "web"):
            pkg = sources_dir / name
            pkg.mkdir()
            (pkg / "__init__.py").write_text(
                "from intellisource.collector.base import BaseCollector, RawContent\n"
                f"class {name.capitalize()}Collector(BaseCollector):\n"
                f"    SOURCE_TYPE = '{name}'\n"
                "    async def collect(self, source_config):\n"
                "        return []\n"
            )

        registry.auto_discover(str(sources_dir))

        assert isinstance(registry.get("rss"), BaseCollector)
        assert isinstance(registry.get("web"), BaseCollector)


# ===================================================================
# AC-T010-6: New sub-packages need only implement BaseCollector + export
# ===================================================================


class TestAutoDiscoverConvention:
    """Verify the convention: a new sources/ sub-package just needs to
    implement BaseCollector and export it in __init__.py to be discovered.
    No registration code modification required."""

    def test_new_subpackage_auto_registered_without_code_change(self, tmp_path):
        """Simulates adding a brand-new source type sub-package. The
        registry discovers it without any changes to existing code."""
        registry = CollectorRegistry()

        sources_dir = tmp_path / "sources"
        sources_dir.mkdir()
        (sources_dir / "__init__.py").write_text("")

        # Pre-existing source
        rss_dir = sources_dir / "rss"
        rss_dir.mkdir()
        (rss_dir / "__init__.py").write_text(
            "from intellisource.collector.base import BaseCollector, RawContent\n"
            "class RSSCollector(BaseCollector):\n"
            "    SOURCE_TYPE = 'rss'\n"
            "    async def collect(self, source_config):\n"
            "        return []\n"
        )

        # NEW source added later
        api_dir = sources_dir / "api"
        api_dir.mkdir()
        (api_dir / "__init__.py").write_text(
            "from intellisource.collector.base import BaseCollector, RawContent\n"
            "class APICollector(BaseCollector):\n"
            "    SOURCE_TYPE = 'api'\n"
            "    async def collect(self, source_config):\n"
            "        return []\n"
        )

        # Single auto_discover call finds both without explicit register()
        registry.auto_discover(str(sources_dir))

        assert isinstance(registry.get("rss"), BaseCollector)
        assert isinstance(registry.get("api"), BaseCollector)

    def test_source_type_derived_from_class_attribute(self, tmp_path):
        """The SOURCE_TYPE class attribute determines the registry key,
        not the directory name."""
        registry = CollectorRegistry()

        sources_dir = tmp_path / "sources"
        sources_dir.mkdir()
        (sources_dir / "__init__.py").write_text("")
        pkg = sources_dir / "my_custom"
        pkg.mkdir()
        (pkg / "__init__.py").write_text(
            "from intellisource.collector.base import BaseCollector, RawContent\n"
            "class CustomCollector(BaseCollector):\n"
            "    SOURCE_TYPE = 'custom_api'\n"
            "    async def collect(self, source_config):\n"
            "        return []\n"
        )

        registry.auto_discover(str(sources_dir))

        assert isinstance(registry.get("custom_api"), BaseCollector)
