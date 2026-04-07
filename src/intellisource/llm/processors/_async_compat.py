"""Async-to-sync compatibility helper for LLM processors.

Provides a utility to run async coroutines from synchronous code,
handling both cases where an event loop is already running and where
one needs to be created.
"""

from __future__ import annotations

import asyncio
from typing import Any, Coroutine, TypeVar

_T = TypeVar("_T")


def run_async(coro: Coroutine[Any, Any, _T]) -> _T:
    """Run an async coroutine from synchronous code.

    If an event loop is already running (e.g. inside a Jupyter notebook
    or an async framework), the coroutine is submitted to a new thread.
    Otherwise, ``asyncio.run`` is used directly.

    Args:
        coro: The coroutine to execute.

    Returns:
        The result produced by the coroutine.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result()
    else:
        return asyncio.run(coro)
