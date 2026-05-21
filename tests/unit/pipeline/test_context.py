"""Tests for PipelineContext (AC-016).

Covers:
- AC-016: PipelineContext supports inter-processor data via get/set key-value pairs.
"""

from intellisource.pipeline.context import PipelineContext


class TestPipelineContextGetSet:
    """AC-016: PipelineContext supports get/set key-value pair storage."""

    def test_set_and_get_value(self):
        """Setting a key-value pair should be retrievable via get."""
        ctx = PipelineContext()
        ctx.set("source_url", "https://example.com")
        assert ctx.get("source_url") == "https://example.com"

    def test_get_nonexistent_key_returns_none(self):
        """Getting a key that was never set should return None by default."""
        ctx = PipelineContext()
        assert ctx.get("missing_key") is None

    def test_get_with_default_value(self):
        """Getting a nonexistent key with a default should return the default."""
        ctx = PipelineContext()
        result = ctx.get("missing_key", "fallback")
        assert result == "fallback"

    def test_get_existing_key_ignores_default(self):
        """When a key exists, the default parameter should be ignored."""
        ctx = PipelineContext()
        ctx.set("key", "actual_value")
        assert ctx.get("key", "default_value") == "actual_value"

    def test_overwrite_existing_key(self):
        """Setting a key that already exists should overwrite the value."""
        ctx = PipelineContext()
        ctx.set("counter", 1)
        ctx.set("counter", 2)
        assert ctx.get("counter") == 2

    def test_multiple_keys_independent(self):
        """Multiple keys should be stored independently without interference."""
        ctx = PipelineContext()
        ctx.set("key_a", "value_a")
        ctx.set("key_b", "value_b")
        assert ctx.get("key_a") == "value_a"
        assert ctx.get("key_b") == "value_b"

    def test_supports_various_value_types(self):
        """Context supports storing different Python types (str, int, list, dict)."""
        ctx = PipelineContext()
        ctx.set("string", "hello")
        ctx.set("number", 42)
        ctx.set("items", [1, 2, 3])
        ctx.set("metadata", {"author": "test"})

        assert ctx.get("string") == "hello"
        assert ctx.get("number") == 42
        assert ctx.get("items") == [1, 2, 3]
        assert ctx.get("metadata") == {"author": "test"}


class TestPipelineContextSharing:
    """AC-016: PipelineContext can be passed between multiple processors."""

    def test_context_preserves_data_across_mutations(self):
        """Passing context through processors: data set by one is visible to next."""
        ctx = PipelineContext()

        # Processor 1 sets data
        ctx.set("step_1_output", "parsed_content")

        # Processor 2 reads data from processor 1 and adds its own
        assert ctx.get("step_1_output") == "parsed_content"
        ctx.set("step_2_output", "enriched_content")

        # Processor 3 can see both
        assert ctx.get("step_1_output") == "parsed_content"
        assert ctx.get("step_2_output") == "enriched_content"
