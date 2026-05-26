"""统一托管 asyncio 后台任务，隔离取消和异常。"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

from package.runtime.models import TaskEvent, TaskHandle
from package.runtime.task_bus import TaskBus


class TaskSupervisor:
    """为 UI 层和服务层统一创建后台任务。"""

    def __init__(self) -> None:
        """初始化任务编号、任务表和事件总线。"""
        self._next_task_id = 1
        self._tasks: dict[int, asyncio.Task] = {}
        self._bus = TaskBus()

    def create_task(self, scope: str, name: str, coroutine: Coroutine[Any, Any, Any]) -> TaskHandle:
        """注册一个后台任务并返回句柄。"""
        task_id = self._next_task_id
        self._next_task_id += 1
        task = asyncio.create_task(self._run_task(task_id, scope, name, coroutine))
        self._tasks[task_id] = task
        return TaskHandle(task_id, scope, name, task)

    async def _run_task(self, task_id: int, scope: str, name: str, coroutine: Coroutine[Any, Any, Any]) -> None:
        """用统一生命周期事件执行后台任务。"""
        await self._bus.publish(TaskEvent(task_id, scope, name, "queued", "任务已入队"))
        try:
            await self._bus.publish(TaskEvent(task_id, scope, name, "running", "任务执行中"))
            await coroutine
        except asyncio.CancelledError:
            await self._bus.publish(TaskEvent(task_id, scope, name, "cancelled", "任务已取消"))
            raise
        except Exception as exc:
            await self._bus.publish(TaskEvent(task_id, scope, name, "failed", str(exc)))
        else:
            await self._bus.publish(TaskEvent(task_id, scope, name, "success", "任务执行完成"))
        finally:
            self._tasks.pop(task_id, None)

    async def wait(self, task_id: int) -> None:
        """等待指定任务结束，包括取消路径。"""
        task = self._tasks.get(task_id)
        if task is None:
            return
        try:
            await task
        except asyncio.CancelledError:
            return

    def drain_events(self) -> list[TaskEvent]:
        """提取当前所有待消费事件。"""
        return self._bus.drain_nowait()
