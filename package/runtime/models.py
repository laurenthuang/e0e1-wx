"""定义运行时任务事件和句柄模型。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class TaskEvent:
    """描述单个后台任务生命周期事件。"""

    task_id: int
    scope: str
    name: str
    status: str
    message: str = ""


class TaskHandle:
    """暴露给 UI 和业务模块的任务句柄。"""

    def __init__(self, task_id: int, scope: str, name: str, task) -> None:
        """保存任务标识、归属作用域和底层 asyncio 任务。"""
        self.task_id = task_id
        self.scope = scope
        self.name = name
        self._task = task

    def cancel(self) -> None:
        """请求取消关联的 asyncio 任务。"""
        self._task.cancel()

    def done(self) -> bool:
        """返回底层 asyncio 任务是否已经结束。"""
        return self._task.done()
