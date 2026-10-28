"""在同步上下文中运行异步 OpenAI 调用（线程池 + asyncio.run）。"""

from __future__ import annotations

import asyncio
import concurrent.futures
import os
from typing import Any, TypeVar

T = TypeVar("T")

_pool: concurrent.futures.ThreadPoolExecutor | None = None


def _default_pool_workers() -> int:
    raw = os.environ.get("SIA_OPENAI_THREAD_POOL_SIZE", "").strip()
    if raw:
        try:
            return max(1, min(int(raw), 32))
        except ValueError:
            pass
    return 8


def get_thread_pool(*, max_workers: int | None = None) -> concurrent.futures.ThreadPoolExecutor:
    global _pool
    workers = max_workers or _default_pool_workers()
    if _pool is None:
        _pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=workers,
            thread_name_prefix="openai-async",
        )
    return _pool


def run_async(coro: "asyncio.coroutines.Coroutine[Any, Any, T]") -> T:
    """无运行中事件循环时 asyncio.run；否则提交到线程池内 asyncio.run。"""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    return get_thread_pool().submit(asyncio.run, coro).result()


def submit_async(
    coro: "asyncio.coroutines.Coroutine[Any, Any, T]",
    *,
    pool: concurrent.futures.ThreadPoolExecutor | None = None,
) -> concurrent.futures.Future[T]:
    """将协程提交到线程池（线程内 asyncio.run）。"""
    executor = pool or get_thread_pool()
    return executor.submit(run_async, coro)
