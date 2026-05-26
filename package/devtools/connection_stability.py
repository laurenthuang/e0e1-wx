"""提供小程序调试 websocket 连接状态防抖工具。"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable


class MiniappConnectionStabilizer:
    """对小程序短暂断连做宽限确认，避免页面跳转时状态抖动。"""

    def __init__(
        self,
        *,
        notify: Callable[[bool], None],
        on_stable_disconnect: Callable[[], None] | None = None,
        grace_seconds: float = 1.2,
        sleep_func: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        """初始化连接状态回调、稳定断连回调和异步宽限期。"""
        self.notify = notify
        self.on_stable_disconnect = on_stable_disconnect
        self.grace_seconds = max(0.0, float(grace_seconds or 0.0))
        self.sleep_func = sleep_func or asyncio.sleep
        self.connected = False
        self.disconnect_task: asyncio.Task | None = None

    def mark_connected(self) -> None:
        """标记小程序已连接，并取消尚未确认的断连任务。"""
        self.cancel_pending_disconnect()
        self.connected = True
        self.notify(True)

    def mark_disconnected_if_idle(self, has_clients: Callable[[], bool]) -> None:
        """在当前没有客户端时启动断连宽限确认。"""
        if has_clients():
            return
        self.cancel_pending_disconnect()
        self.disconnect_task = asyncio.create_task(self._confirm_disconnect_after_grace(has_clients))

    async def _confirm_disconnect_after_grace(self, has_clients: Callable[[], bool]) -> None:
        """等待宽限期后再次确认无客户端，再发布稳定离线状态。"""
        try:
            await self.sleep_func(self.grace_seconds)
            if has_clients():
                return
            if self.connected:
                self.connected = False
                self.notify(False)
            if self.on_stable_disconnect is not None:
                self.on_stable_disconnect()
        finally:
            if self.disconnect_task is asyncio.current_task():
                self.disconnect_task = None

    def cancel_pending_disconnect(self) -> None:
        """取消尚未完成的断连确认任务。"""
        task = self.disconnect_task
        self.disconnect_task = None
        if task is not None and not task.done():
            task.cancel()

    async def wait_pending_disconnect(self) -> None:
        """等待当前断连确认任务结束，供测试复用。"""
        task = self.disconnect_task
        if task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def shutdown(self) -> None:
        """停止稳定器并取消挂起的断连确认任务。"""
        task = self.disconnect_task
        self.disconnect_task = None
        if task is not None and not task.done():
            task.cancel()
        if task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await task
