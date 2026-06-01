"""PipelineLoader abstraction.

Defines the `PipelineLoader` protocol that lower layers (e.g. ``scheduler``)
depend on to resolve a pipeline name to its parsed configuration. The concrete
implementation lives in ``composition`` — the only layer permitted to import
``agent`` — so ``core`` carries no upward dependency on business packages.
"""

from __future__ import annotations

from typing import Any, Protocol


class PipelineLoader(Protocol):
    """Resolve a pipeline yaml name to a parsed pipeline configuration."""

    def load(self, name: str) -> Any: ...
