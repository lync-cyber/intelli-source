"""Tests for PriorityQueue with separate queues for user/background requests.

Covers:
- AC-032: User interaction requests (priority=high) and background processing
  requests (priority=normal/low) use independent queues
- AC-T021-1: PriorityQueue ensures high-priority requests execute first
"""

from __future__ import annotations

import asyncio

import pytest
from intellisource.llm.priority_queue import PriorityLevel, PriorityQueue, QueuedRequest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def queue() -> PriorityQueue:
    """Create a fresh PriorityQueue instance."""
    return PriorityQueue()


# ===================================================================
# AC-032: Independent queues for user-interactive vs background
# ===================================================================


class TestIndependentQueues:
    """Verify user-interactive and background requests use separate queues."""

    @pytest.mark.asyncio
    async def test_high_priority_goes_to_interactive_queue(
        self, queue: PriorityQueue
    ) -> None:
        """A request with priority=high is placed in the interactive queue."""
        request = QueuedRequest(
            prompt="user question",
            model="gpt-4o-mini",
            priority=PriorityLevel.HIGH,
        )
        await queue.enqueue(request)

        assert queue.interactive_queue_size() == 1
        assert queue.background_queue_size() == 0

    @pytest.mark.asyncio
    async def test_normal_priority_goes_to_background_queue(
        self, queue: PriorityQueue
    ) -> None:
        """A request with priority=normal is placed in the background queue."""
        request = QueuedRequest(
            prompt="background task",
            model="gpt-4o-mini",
            priority=PriorityLevel.NORMAL,
        )
        await queue.enqueue(request)

        assert queue.interactive_queue_size() == 0
        assert queue.background_queue_size() == 1

    @pytest.mark.asyncio
    async def test_low_priority_goes_to_background_queue(
        self, queue: PriorityQueue
    ) -> None:
        """A request with priority=low is placed in the background queue."""
        request = QueuedRequest(
            prompt="low-priority batch job",
            model="gpt-4o-mini",
            priority=PriorityLevel.LOW,
        )
        await queue.enqueue(request)

        assert queue.interactive_queue_size() == 0
        assert queue.background_queue_size() == 1

    @pytest.mark.asyncio
    async def test_mixed_requests_routed_to_correct_queues(
        self, queue: PriorityQueue
    ) -> None:
        """Multiple requests with different priorities are routed correctly."""
        high = QueuedRequest(
            prompt="urgent", model="gpt-4o-mini", priority=PriorityLevel.HIGH
        )
        normal = QueuedRequest(
            prompt="normal", model="gpt-4o-mini", priority=PriorityLevel.NORMAL
        )
        low = QueuedRequest(
            prompt="low", model="gpt-4o-mini", priority=PriorityLevel.LOW
        )
        await queue.enqueue(high)
        await queue.enqueue(normal)
        await queue.enqueue(low)

        assert queue.interactive_queue_size() == 1
        assert queue.background_queue_size() == 2


# ===================================================================
# AC-T021-1: High priority requests execute first
# ===================================================================


class TestPriorityOrdering:
    """Verify high-priority requests are dequeued before lower priorities."""

    @pytest.mark.asyncio
    async def test_dequeue_returns_high_before_normal(
        self, queue: PriorityQueue
    ) -> None:
        """When both queues have items, dequeue returns high-priority first."""
        normal_req = QueuedRequest(
            prompt="background", model="gpt-4o-mini", priority=PriorityLevel.NORMAL
        )
        high_req = QueuedRequest(
            prompt="interactive", model="gpt-4o-mini", priority=PriorityLevel.HIGH
        )
        # Enqueue normal first, then high
        await queue.enqueue(normal_req)
        await queue.enqueue(high_req)

        first = await queue.dequeue()
        assert first.priority == PriorityLevel.HIGH
        assert first.prompt == "interactive"

    @pytest.mark.asyncio
    async def test_dequeue_returns_normal_before_low(
        self, queue: PriorityQueue
    ) -> None:
        """Within the background queue, normal-priority comes before low."""
        low_req = QueuedRequest(
            prompt="batch", model="gpt-4o-mini", priority=PriorityLevel.LOW
        )
        normal_req = QueuedRequest(
            prompt="normal", model="gpt-4o-mini", priority=PriorityLevel.NORMAL
        )
        await queue.enqueue(low_req)
        await queue.enqueue(normal_req)

        first = await queue.dequeue()
        assert first.priority == PriorityLevel.NORMAL

    @pytest.mark.asyncio
    async def test_dequeue_drains_interactive_before_background(
        self, queue: PriorityQueue
    ) -> None:
        """All interactive requests are served before any background request."""
        for i in range(3):
            await queue.enqueue(
                QueuedRequest(
                    prompt=f"high-{i}",
                    model="gpt-4o-mini",
                    priority=PriorityLevel.HIGH,
                )
            )
        await queue.enqueue(
            QueuedRequest(
                prompt="normal-0", model="gpt-4o-mini", priority=PriorityLevel.NORMAL
            )
        )

        results = []
        for _ in range(4):
            results.append(await queue.dequeue())

        # First 3 should all be high priority
        for r in results[:3]:
            assert r.priority == PriorityLevel.HIGH
        assert results[3].priority == PriorityLevel.NORMAL

    @pytest.mark.asyncio
    async def test_dequeue_from_empty_queue_blocks(self, queue: PriorityQueue) -> None:
        """Dequeue on an empty queue should not return immediately (blocks/waits)."""
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(queue.dequeue(), timeout=0.1)

    @pytest.mark.asyncio
    async def test_total_size_reflects_all_queues(self, queue: PriorityQueue) -> None:
        """total_size() returns the sum of both queues."""
        await queue.enqueue(
            QueuedRequest(prompt="a", model="gpt-4o-mini", priority=PriorityLevel.HIGH)
        )
        await queue.enqueue(
            QueuedRequest(prompt="b", model="gpt-4o-mini", priority=PriorityLevel.LOW)
        )

        assert queue.total_size() == 2
