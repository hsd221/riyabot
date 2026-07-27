"""Strong references for fire-and-forget asyncio tasks.

事件循环只持有任务的弱引用，`asyncio.create_task(...)` 的返回值一旦被丢弃，
任务就可能在执行到一半时被垃圾回收，表现为"消息偶尔丢失"这类难以复现的问题。
所有不需要 await 的后台协程都应通过本模块调度。
"""

from __future__ import annotations

import asyncio
from typing import Any, Coroutine, Optional

from src.common.logger import get_logger


logger = get_logger("background_tasks")

_background_tasks: set[asyncio.Task[Any]] = set()


def _log_task_result(task: asyncio.Task[Any]) -> None:
    _background_tasks.discard(task)
    if task.cancelled():
        return
    error = task.exception()
    if error is not None:
        logger.error(f"后台任务 {task.get_name()} 异常退出: {type(error).__name__}: {error}")


def spawn_background_task(
    coroutine: Coroutine[Any, Any, Any],
    *,
    name: Optional[str] = None,
) -> asyncio.Task[Any]:
    """调度一个后台协程，并在其结束前保持强引用。"""

    task = asyncio.create_task(coroutine, name=name)
    _background_tasks.add(task)
    task.add_done_callback(_log_task_result)
    return task


def active_background_task_count() -> int:
    """返回仍在运行的后台任务数量，供健康检查与测试使用。"""

    return sum(not task.done() for task in _background_tasks)
