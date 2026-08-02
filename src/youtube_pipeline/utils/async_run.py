"""Run async coroutines from sync code, including inside a live event loop."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar

T = TypeVar("T")


def run_coro_sync(factory: Callable[[], Awaitable[T]]) -> T:
    """Run ``factory()`` to completion from sync code.

    Always executes in a worker thread with a fresh event loop. This avoids
    nested-loop errors inside FastAPI handlers and prevents half-created
    coroutines from being abandoned when the caller already has a running loop.
    """

    def _runner() -> T:
        return asyncio.run(factory())

    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(_runner).result()
