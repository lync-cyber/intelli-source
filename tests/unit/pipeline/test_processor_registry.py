"""Unit tests for PROCESSOR_REGISTRY (T-096 AC-1, AC-9).

Verifies that:
- PROCESSOR_REGISTRY exists in intellisource.pipeline.registry
- It contains at least HTMLParser, ContentDedup, KeywordTagger entries
- Retrieving an unknown key raises ValueError with a descriptive message
- Each registered value is a class (not an instance) that subclasses BaseProcessor
"""

from __future__ import annotations

import pytest

from intellisource.pipeline.base import BaseProcessor


class TestProcessorRegistryExists:
    """AC-1 / AC-9: PROCESSOR_REGISTRY is importable from pipeline.registry."""

    def test_processor_registry_importable(self) -> None:
        """PROCESSOR_REGISTRY must be importable from pipeline.registry."""
        from intellisource.pipeline.registry import PROCESSOR_REGISTRY  # noqa: PLC0415

        assert PROCESSOR_REGISTRY is not None, (
            "PROCESSOR_REGISTRY must not be None after import"
        )

    def test_processor_registry_is_dict(self) -> None:
        """PROCESSOR_REGISTRY must be a dict[str, type[BaseProcessor]]."""
        from intellisource.pipeline.registry import PROCESSOR_REGISTRY  # noqa: PLC0415

        assert isinstance(PROCESSOR_REGISTRY, dict), (
            f"Expected PROCESSOR_REGISTRY to be dict, got {type(PROCESSOR_REGISTRY)}"
        )


class TestProcessorRegistryContents:
    """AC-1 / AC-9: Registry contains the required processor classes."""

    def test_html_parser_registered(self) -> None:
        """PROCESSOR_REGISTRY must contain an 'HTMLParser' key."""
        from intellisource.pipeline.registry import PROCESSOR_REGISTRY  # noqa: PLC0415

        assert "HTMLParser" in PROCESSOR_REGISTRY, (
            f"'HTMLParser' not found in PROCESSOR_REGISTRY keys: "
            f"{sorted(PROCESSOR_REGISTRY.keys())}"
        )

    def test_content_dedup_registered(self) -> None:
        """PROCESSOR_REGISTRY must contain a 'ContentDedup' key."""
        from intellisource.pipeline.registry import PROCESSOR_REGISTRY  # noqa: PLC0415

        assert "ContentDedup" in PROCESSOR_REGISTRY, (
            f"'ContentDedup' not found in PROCESSOR_REGISTRY keys: "
            f"{sorted(PROCESSOR_REGISTRY.keys())}"
        )

    def test_keyword_tagger_registered(self) -> None:
        """PROCESSOR_REGISTRY must contain a 'KeywordTagger' key."""
        from intellisource.pipeline.registry import PROCESSOR_REGISTRY  # noqa: PLC0415

        assert "KeywordTagger" in PROCESSOR_REGISTRY, (
            f"'KeywordTagger' not found in PROCESSOR_REGISTRY keys: "
            f"{sorted(PROCESSOR_REGISTRY.keys())}"
        )

    def test_registered_values_are_base_processor_subclasses(self) -> None:
        """Every value in PROCESSOR_REGISTRY must subclass BaseProcessor."""
        from intellisource.pipeline.registry import PROCESSOR_REGISTRY  # noqa: PLC0415

        for name, cls in PROCESSOR_REGISTRY.items():
            assert isinstance(cls, type), (
                f"PROCESSOR_REGISTRY[{name!r}] must be a class, got {type(cls)}"
            )
            assert issubclass(cls, BaseProcessor), (
                f"PROCESSOR_REGISTRY[{name!r}] ({cls}) must subclass BaseProcessor"
            )


class TestProcessorRegistryLookup:
    """AC-1 / AC-9: known keys resolve, unknown keys raise ValueError."""

    def test_known_key_returns_class(self) -> None:
        """Looking up 'HTMLParser' returns the HTMLParser class itself."""
        from intellisource.pipeline.processors.parser import HTMLParser  # noqa: PLC0415
        from intellisource.pipeline.registry import PROCESSOR_REGISTRY  # noqa: PLC0415

        result = PROCESSOR_REGISTRY["HTMLParser"]
        assert result is HTMLParser, (
            f"PROCESSOR_REGISTRY['HTMLParser'] must be HTMLParser class, got {result}"
        )

    def test_unknown_key_raises_value_error(self) -> None:
        """AC-1/AC-9: Accessing an unknown processor name must raise ValueError."""

        with pytest.raises(ValueError, match="Unknown processor"):
            # Direct dict access would raise KeyError — the registry must expose a
            # helper that raises ValueError. Test both the module-level lookup helper
            # and confirm bare dict access alone is not the contract.
            from intellisource.pipeline.registry import get_processor  # noqa: PLC0415

            get_processor("NonExistentProcessorXYZ")

    def test_unknown_key_message_contains_name(self) -> None:
        """ValueError message must include the unknown processor name."""
        from intellisource.pipeline.registry import get_processor  # noqa: PLC0415

        bad_name = "DefinitelyMissingProcessor"
        with pytest.raises(ValueError, match=bad_name):
            get_processor(bad_name)


class TestBuildProcessorsFromConfig:
    """AC-2: _build_processors_from_config uses PROCESSOR_REGISTRY, not PassThrough."""

    def test_build_processors_uses_registry(self) -> None:
        """_build_processors_from_config instantiates processors via registry."""
        from intellisource.agent.factory import (
            _build_processors_from_config,  # noqa: PLC0415
        )
        from intellisource.agent.pipeline import PipelineConfig  # noqa: PLC0415
        from intellisource.pipeline.processors.parser import HTMLParser  # noqa: PLC0415

        # Build a minimal PipelineConfig with one known step
        config = PipelineConfig(
            name="test-pipe",
            mode="strict",
            steps=[{"processor": "HTMLParser", "params": {}}],
            max_steps=10,
            on_failure="abort",
        )
        processors = _build_processors_from_config(config)

        assert len(processors) == 1, f"Expected 1 processor, got {len(processors)}"
        assert isinstance(processors[0], HTMLParser), (
            f"Expected HTMLParser instance, got {type(processors[0])}"
        )

    def test_build_processors_no_pass_through(self) -> None:
        """After AC-3: _PassThroughProcessor must NOT appear in factory output."""
        from intellisource.agent import factory as factory_mod  # noqa: PLC0415

        # _PassThroughProcessor should have been deleted (AC-3)
        assert not hasattr(factory_mod, "_PassThroughProcessor"), (
            "AC-3: _PassThroughProcessor class must be removed from agent/factory.py"
        )

    def test_unknown_step_raises_value_error(self) -> None:
        """An unknown processor name in steps must raise ValueError at build time."""
        from intellisource.agent.factory import (
            _build_processors_from_config,  # noqa: PLC0415
        )
        from intellisource.agent.pipeline import PipelineConfig  # noqa: PLC0415

        config = PipelineConfig(
            name="bad-pipe",
            mode="strict",
            steps=[{"processor": "ThisDoesNotExist", "params": {}}],
            max_steps=10,
            on_failure="abort",
        )
        with pytest.raises(ValueError, match="Unknown processor"):
            _build_processors_from_config(config)
