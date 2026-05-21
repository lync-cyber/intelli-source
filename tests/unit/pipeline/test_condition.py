"""Tests for ConditionEvaluator and ConditionalProcessor (AC-014, AC-T017-1, AC-T017-3).

Covers:
- AC-014: Processors can be configured with condition expressions; skip on no match.
- AC-T017-1: Condition expressions support content_type, tags, source_type rules.
- AC-T017-3: Conditional branching supports if-else routing to processor sub-chains.
"""

from intellisource.pipeline.base import BaseProcessor
from intellisource.pipeline.condition import ConditionalProcessor, ConditionEvaluator
from intellisource.pipeline.context import PipelineContext

# ---------------------------------------------------------------------------
# Helper: concrete processor stubs for testing conditional routing
# ---------------------------------------------------------------------------


class _MarkerProcessor(BaseProcessor):
    """A stub processor that sets a marker key in the context."""

    def __init__(self, marker: str) -> None:
        self._marker = marker

    def process(self, context: PipelineContext) -> PipelineContext:
        context.set("executed_by", self._marker)
        return context


# ===========================================================================
# ConditionEvaluator
# ===========================================================================


class TestConditionEvaluatorEqOperator:
    """AC-T017-1: 'eq' operator checks exact equality on scalar fields."""

    def test_eq_content_type_match(self):
        """evaluate should return True when content_type equals expected value."""
        ctx = PipelineContext()
        ctx.set("content_type", "article")

        evaluator = ConditionEvaluator()
        condition = {"field": "content_type", "operator": "eq", "value": "article"}
        assert evaluator.evaluate(condition, ctx) is True

    def test_eq_content_type_no_match(self):
        """evaluate should return False when content_type differs."""
        ctx = PipelineContext()
        ctx.set("content_type", "video")

        evaluator = ConditionEvaluator()
        condition = {"field": "content_type", "operator": "eq", "value": "article"}
        assert evaluator.evaluate(condition, ctx) is False

    def test_eq_source_type(self):
        """evaluate should work with source_type field."""
        ctx = PipelineContext()
        ctx.set("source_type", "rss")

        evaluator = ConditionEvaluator()
        condition = {"field": "source_type", "operator": "eq", "value": "rss"}
        assert evaluator.evaluate(condition, ctx) is True


class TestConditionEvaluatorNeqOperator:
    """AC-T017-1: 'neq' operator checks inequality on scalar fields."""

    def test_neq_returns_true_when_different(self):
        """evaluate should return True when field value differs from condition value."""
        ctx = PipelineContext()
        ctx.set("content_type", "video")

        evaluator = ConditionEvaluator()
        condition = {"field": "content_type", "operator": "neq", "value": "article"}
        assert evaluator.evaluate(condition, ctx) is True

    def test_neq_returns_false_when_equal(self):
        """evaluate should return False when field value matches condition value."""
        ctx = PipelineContext()
        ctx.set("content_type", "article")

        evaluator = ConditionEvaluator()
        condition = {"field": "content_type", "operator": "neq", "value": "article"}
        assert evaluator.evaluate(condition, ctx) is False


class TestConditionEvaluatorInOperator:
    """AC-T017-1: 'in' operator checks membership in a list of values."""

    def test_in_matches_when_value_in_list(self):
        """evaluate should return True when field value is in the given list."""
        ctx = PipelineContext()
        ctx.set("content_type", "article")

        evaluator = ConditionEvaluator()
        condition = {
            "field": "content_type",
            "operator": "in",
            "value": ["article", "blog"],
        }
        assert evaluator.evaluate(condition, ctx) is True

    def test_in_no_match_when_value_not_in_list(self):
        """evaluate should return False when field value is not in the list."""
        ctx = PipelineContext()
        ctx.set("content_type", "video")

        evaluator = ConditionEvaluator()
        condition = {
            "field": "content_type",
            "operator": "in",
            "value": ["article", "blog"],
        }
        assert evaluator.evaluate(condition, ctx) is False


class TestConditionEvaluatorNotInOperator:
    """AC-T017-1: 'not_in' operator checks absence from a list of values."""

    def test_not_in_returns_true_when_absent(self):
        """evaluate should return True when field value is not in the list."""
        ctx = PipelineContext()
        ctx.set("source_type", "api")

        evaluator = ConditionEvaluator()
        condition = {
            "field": "source_type",
            "operator": "not_in",
            "value": ["rss", "web"],
        }
        assert evaluator.evaluate(condition, ctx) is True

    def test_not_in_returns_false_when_present(self):
        """evaluate should return False when field value is in the list."""
        ctx = PipelineContext()
        ctx.set("source_type", "rss")

        evaluator = ConditionEvaluator()
        condition = {
            "field": "source_type",
            "operator": "not_in",
            "value": ["rss", "web"],
        }
        assert evaluator.evaluate(condition, ctx) is False


class TestConditionEvaluatorContainsOperator:
    """AC-T017-1: 'contains' operator checks if a collection field contains a value."""

    def test_tags_contains_matching_tag(self):
        """evaluate should return True when tags list contains the target tag."""
        ctx = PipelineContext()
        ctx.set("tags", ["python", "ai", "tutorial"])

        evaluator = ConditionEvaluator()
        condition = {"field": "tags", "operator": "contains", "value": "ai"}
        assert evaluator.evaluate(condition, ctx) is True

    def test_tags_contains_no_matching_tag(self):
        """evaluate returns False when tags list lacks the target tag."""
        ctx = PipelineContext()
        ctx.set("tags", ["python", "tutorial"])

        evaluator = ConditionEvaluator()
        condition = {"field": "tags", "operator": "contains", "value": "ai"}
        assert evaluator.evaluate(condition, ctx) is False


class TestConditionEvaluatorEdgeCases:
    """AC-014 / AC-T017-1: Edge cases for condition evaluation."""

    def test_missing_field_returns_false(self):
        """evaluate should return False when the field does not exist in context."""
        ctx = PipelineContext()
        # content_type is never set

        evaluator = ConditionEvaluator()
        condition = {"field": "content_type", "operator": "eq", "value": "article"}
        assert evaluator.evaluate(condition, ctx) is False

    def test_tags_field_none_with_contains(self):
        """evaluate returns False when tags is None and operator is contains."""
        ctx = PipelineContext()
        ctx.set("tags", None)

        evaluator = ConditionEvaluator()
        condition = {"field": "tags", "operator": "contains", "value": "ai"}
        assert evaluator.evaluate(condition, ctx) is False


# ===========================================================================
# ConditionalProcessor (if-else routing)
# ===========================================================================


class TestConditionalProcessorIfBranch:
    """AC-T017-3: When condition is met, the if_processor should execute."""

    def test_if_processor_executes_when_condition_true(self):
        """ConditionalProcessor delegates to if_processor when condition is True."""
        ctx = PipelineContext()
        ctx.set("content_type", "article")

        condition = {"field": "content_type", "operator": "eq", "value": "article"}
        if_proc = _MarkerProcessor("if_branch")
        else_proc = _MarkerProcessor("else_branch")

        cond_proc = ConditionalProcessor(
            condition=condition,
            if_processor=if_proc,
            else_processor=else_proc,
        )
        result = cond_proc.process(ctx)
        assert result.get("executed_by") == "if_branch"


class TestConditionalProcessorElseBranch:
    """AC-T017-3: When condition is not met, the else_processor should execute."""

    def test_else_processor_executes_when_condition_false(self):
        """ConditionalProcessor delegates to else_processor when condition False."""
        ctx = PipelineContext()
        ctx.set("content_type", "video")

        condition = {"field": "content_type", "operator": "eq", "value": "article"}
        if_proc = _MarkerProcessor("if_branch")
        else_proc = _MarkerProcessor("else_branch")

        cond_proc = ConditionalProcessor(
            condition=condition,
            if_processor=if_proc,
            else_processor=else_proc,
        )
        result = cond_proc.process(ctx)
        assert result.get("executed_by") == "else_branch"


class TestConditionalProcessorNoElse:
    """AC-T017-3: When else_processor omitted and condition False, ctx flows on."""

    def test_no_else_processor_passes_through(self):
        """Without else_processor and condition False, context is returned unchanged."""
        ctx = PipelineContext()
        ctx.set("content_type", "video")
        ctx.set("original_data", "preserved")

        condition = {"field": "content_type", "operator": "eq", "value": "article"}
        if_proc = _MarkerProcessor("if_branch")

        cond_proc = ConditionalProcessor(
            condition=condition,
            if_processor=if_proc,
        )
        result = cond_proc.process(ctx)

        # if_processor should NOT have executed
        assert result.get("executed_by") is None
        # original data should be preserved
        assert result.get("original_data") == "preserved"


class TestConditionalProcessorSkipBehavior:
    """AC-014: Processor is skipped entirely when condition is not met."""

    def test_skip_leaves_context_unmodified(self):
        """When condition fails and no else_processor, context is not mutated."""
        ctx = PipelineContext()
        ctx.set("source_type", "web")
        ctx.set("step_count", 0)

        condition = {"field": "source_type", "operator": "eq", "value": "api"}
        if_proc = _MarkerProcessor("should_not_run")

        cond_proc = ConditionalProcessor(
            condition=condition,
            if_processor=if_proc,
        )
        result = cond_proc.process(ctx)

        assert result.get("executed_by") is None
        assert result.get("step_count") == 0
