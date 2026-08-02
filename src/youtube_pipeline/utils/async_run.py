"""Run async coroutines from sync code, including inside a live event loop."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar

T = TypeVar("T")


def run_coro_sync(factory: Callable[[], Awaitable[T]]) -> T:
    """Run ``factory()`` to completion from sync code.

    Uses ``asyncio.run`` when no loop is active. When called from a running
    loop (e.g. FastAPI ``async def`` handlers), runs the coroutine in a
    worker thread with its own event loop — nested ``asyncio.run`` /
    ``run_until_complete`` on the same thread would raise.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())

    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(factory())).result()
