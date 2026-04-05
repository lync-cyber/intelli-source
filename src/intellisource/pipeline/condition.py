"""ConditionEvaluator and ConditionalProcessor for conditional pipeline routing."""

from __future__ import annotations

from typing import Any

from intellisource.pipeline.base import BaseProcessor
from intellisource.pipeline.context import PipelineContext


class ConditionEvaluator:
    """Evaluates condition expressions against a PipelineContext."""

    def evaluate(self, condition: dict[str, Any], context: PipelineContext) -> bool:
        """Evaluate a condition dict against the given context.

        Condition format: {"field": str, "operator": str, "value": Any}
        Supported operators: eq, neq, in, not_in, contains.
        """
        field: str = condition["field"]
        operator: str = condition["operator"]
        value: Any = condition["value"]

        field_value: Any = context.get(field)

        if operator == "eq":
            return bool(field_value == value)
        if operator == "neq":
            return bool(field_value != value)
        if operator == "in":
            return bool(field_value in value)
        if operator == "not_in":
            return bool(field_value not in value)
        if operator == "contains":
            if field_value is None:
                return False
            return bool(value in field_value)

        return False


class ConditionalProcessor(BaseProcessor):
    """Routes processing to if_processor or else_processor based on a condition."""

    def __init__(
        self,
        condition: dict[str, Any],
        if_processor: BaseProcessor,
        else_processor: BaseProcessor | None = None,
    ) -> None:
        self._condition = condition
        self._if_processor = if_processor
        self._else_processor = else_processor
        self._evaluator = ConditionEvaluator()

    def process(self, context: PipelineContext) -> PipelineContext:
        """Evaluate condition and delegate to the appropriate processor."""
        if self._evaluator.evaluate(self._condition, context):
            return self._if_processor.process(context)
        if self._else_processor is not None:
            return self._else_processor.process(context)
        return context
