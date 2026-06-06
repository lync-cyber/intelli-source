"""Fallback manager for LLM degradation handling.

Maintains a mapping of task types to fallback functions and records
fallback events to LLMCallLog with status=fallback.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable


class FallbackManager:
    """Manages degradation fallback functions for LLM task types.

    Args:
        fallback_registry: Mapping of task_type to fallback callable.
        call_log: Async logger with a ``record`` method for logging fallback events.
    """

    def __init__(
        self,
        fallback_registry: dict[str, Callable[..., Any]],
        call_log: Any,
    ) -> None:
        self._fallback_registry = dict(fallback_registry)
        self._call_log = call_log

    @property
    def fallback_registry(self) -> dict[str, Callable[..., Any]]:
        """Return the current fallback registry."""
        return self._fallback_registry

    async def execute_fallback(
        self,
        task_type: str,
        input_data: Any,
    ) -> Any:
        """Execute the fallback function for the given task type.

        Args:
            task_type: The task type to degrade.
            input_data: Input to pass to the fallback function.

        Returns:
            The result of the fallback function.

        Raises:
            ValueError: If task_type is not registered or input_data is None.
        """
        if input_data is None:
            raise ValueError("input_data must not be None")
        if task_type not in self._fallback_registry:
            raise KeyError(f"No fallback registered for task type: {task_type}")
        fallback_fn = self._fallback_registry[task_type]
        result = await asyncio.to_thread(fallback_fn, input_data)
        await self._call_log.record(
            task_type=task_type,
            status="fallback",
            result=result,
        )
        return result
