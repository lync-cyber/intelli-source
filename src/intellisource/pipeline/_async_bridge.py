"""Run an async coroutine from synchronous pipeline-processor code.

Pipeline processors execute synchronously (the worker offloads them via
``asyncio.to_thread``) but some need to await LLM-gateway coroutines. This
bridges both the no-running-loop case (``asyncio.run`` works directly) and the
running-loop case (defer to a fresh thread) without binding a connection pool
to a loop that later dies.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
from typing import Any


def run_coro(coro: Any) -> Any:
    """Synchronously drive *coro* to completion from sync code."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(asyncio.run, coro)
        return future.result()
