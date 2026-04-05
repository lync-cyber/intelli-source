"""CollectorRegistry: registration and auto-discovery of collectors."""

from __future__ import annotations

import importlib.util
import inspect
import sys
from pathlib import Path

from intellisource.collector.base import BaseCollector
from intellisource.core.errors import CollectorError, ErrorCategory


class CollectorRegistry:
    """Registry for mapping source types to collector classes."""

    def __init__(self) -> None:
        self._registry: dict[str, type[BaseCollector]] = {}

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
        return cls()

    def auto_discover(self, sources_dir: str) -> None:
        """Scan sources_dir for sub-packages containing BaseCollector subclasses.

        Each sub-package's __init__.py is imported and inspected for classes
        that extend BaseCollector. Found classes are registered using their
        SOURCE_TYPE class attribute as the registry key.
        """
        sources_path = Path(sources_dir)
        for child in sorted(sources_path.iterdir()):
            if not child.is_dir():
                continue
            init_file = child / "__init__.py"
            if not init_file.exists():
                continue

            module_name = f"intellisource.collector.sources.{child.name}"
            spec = importlib.util.spec_from_file_location(module_name, str(init_file))
            if spec is None or spec.loader is None:
                continue

            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)

            for _name, obj in inspect.getmembers(module, inspect.isclass):
                if (
                    issubclass(obj, BaseCollector)
                    and obj is not BaseCollector
                    and hasattr(obj, "SOURCE_TYPE")
                ):
                    source_type: str = getattr(obj, "SOURCE_TYPE")
                    self._registry[source_type] = obj
