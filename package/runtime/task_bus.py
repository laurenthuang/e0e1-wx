"""封装 supervisor 使用的任务事件队列。"""

from __future__ import annotations

import asyncio

from package.runtime.models import TaskEvent


class TaskBus:
    """为任务 supervisor 提供可非阻塞消费的事件缓冲。"""

    def __init__(self) -> None:
        """初始化异步事件队列。"""
        self._queue: asyncio.Queue[TaskEvent] = asyncio.Queue()

    async def publish(self, event: TaskEvent) -> None:
        """发布一个任务生命周期事件。"""
        await self._queue.put(event)

    def drain_nowait(self) -> list[TaskEvent]:
        """非阻塞提取当前所有待消费事件。"""
        events: list[TaskEvent] = []
        while True:
            try:
                events.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        return events
