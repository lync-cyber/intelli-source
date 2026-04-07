"""Priority queue with separate interactive and background queues (T-021)."""

from __future__ import annotations

import asyncio
import enum
from dataclasses import dataclass


class PriorityLevel(enum.Enum):
    """Priority levels for LLM requests."""

    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


@dataclass
class QueuedRequest:
    """A queued LLM request."""

    prompt: str
    model: str
    priority: PriorityLevel


class PriorityQueue:
    """Two-tier priority queue: interactive (HIGH) and background (NORMAL/LOW)."""

    def __init__(self) -> None:
        self._interactive: asyncio.Queue[QueuedRequest] = asyncio.Queue()
        self._background: asyncio.Queue[tuple[int, int, QueuedRequest]] = (
            asyncio.Queue()
        )
        self._seq = 0
        self._notify: asyncio.Event = asyncio.Event()

    async def enqueue(self, request: QueuedRequest) -> None:
        """Add a request to the appropriate queue."""
        if request.priority == PriorityLevel.HIGH:
            await self._interactive.put(request)
        else:
            order = 0 if request.priority == PriorityLevel.NORMAL else 1
            self._seq += 1
            await self._background.put((order, self._seq, request))
        self._notify.set()

    async def dequeue(self) -> QueuedRequest:
        """Dequeue next request. Interactive queue has priority over background."""
        while True:
            if not self._interactive.empty():
                return self._interactive.get_nowait()
            if not self._background.empty():
                # Scan for highest priority (lowest order value)
                items: list[tuple[int, int, QueuedRequest]] = []
                while not self._background.empty():
                    items.append(self._background.get_nowait())
                items.sort(key=lambda x: (x[0], x[1]))
                result = items[0][2]
                for item in items[1:]:
                    await self._background.put(item)
                return result
            self._notify.clear()
            await self._notify.wait()

    def interactive_queue_size(self) -> int:
        """Return the number of items in the interactive queue."""
        return self._interactive.qsize()

    def background_queue_size(self) -> int:
        """Return the number of items in the background queue."""
        return self._background.qsize()

    def total_size(self) -> int:
        """Return the total number of items across all queues."""
        return self.interactive_queue_size() + self.background_queue_size()
