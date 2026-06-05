"""QueueMixin: priority-queue request handling for LLMGateway."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from intellisource.llm.priority_queue import PriorityLevel, PriorityQueue, QueuedRequest

if TYPE_CHECKING:
    from intellisource.llm.gateway._proto import _GatewayProto


class _QueueMixin:
    """Provides enqueue_request() and process_queue_item()."""

    _priority_queue: PriorityQueue | None
    _INTERACTIVE_TASK_TYPES: frozenset[str]

    async def enqueue_request(
        self: _GatewayProto,
        prompt: str,
        model: str,
        task_type: str | None = None,
    ) -> None:
        """Enqueue an LLM request into the priority queue.

        Interactive task types (search, chat, interactive, query) use
        PriorityLevel.HIGH; all other task types — including task_type=None —
        use PriorityLevel.NORMAL.
        """
        if self._priority_queue is None:
            raise RuntimeError("No priority_queue configured on LLMGateway")
        priority = (
            PriorityLevel.HIGH
            if task_type in self._INTERACTIVE_TASK_TYPES
            else PriorityLevel.NORMAL
        )
        req = QueuedRequest(prompt=prompt, model=model, priority=priority)
        await self._priority_queue.enqueue(req)

    async def process_queue_item(self: _GatewayProto) -> Any:
        """Dequeue one request from the priority queue and execute it via litellm.

        Returns the LLM response or None if no queue is configured.
        """
        if self._priority_queue is None:
            return None
        req = await self._priority_queue.dequeue()
        call_kwargs: dict[str, Any] = {
            "model": req.model,
            "messages": [{"role": "user", "content": req.prompt}],
        }
        return await self._call_with_retry(
            call_kwargs=call_kwargs,
            prompt=req.prompt,
            task_type=None,
        )
