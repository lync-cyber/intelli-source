"""PipelineLoader: resolves pipeline yaml names to PipelineConfig instances.

Lives in `core` (an unlayered cross-cutting module) so that both
`composition` (top-down layer) and `scheduler` (a lower layer) can import
it without violating the import-linter layered architecture contract.
"""

from __future__ import annotations

from intellisource.agent.pipeline import PipelineConfig
from intellisource.agent.tools import load_pipeline_config


class PipelineLoader:
    """Resolve a pipeline yaml name to a `PipelineConfig` instance.

    Wraps `intellisource.agent.tools.load_pipeline_config` so that the
    `CeleryTasks.run_pipeline` consumer can hold a stable, mockable
    dependency instead of a free function.
    """

    def load(self, name: str) -> PipelineConfig:
        return load_pipeline_config(name)


def build_pipeline_loader() -> PipelineLoader:
    return PipelineLoader()
