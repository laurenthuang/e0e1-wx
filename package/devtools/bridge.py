"""Bridge abstractions used by the shared DevTools worker."""

from __future__ import annotations

import contextlib
import json
from typing import Callable, Protocol

from package.devtools.engine import DebugEngine, normalize_proxy_message


class EngineBridge(Protocol):
    """Protocol for the real or test bridge used by the worker."""

    async def start(
        self,
        session: dict,
        debug_port: int,
        cdp_port: int,
        status_callback: Callable[[dict], None],
    ) -> None:
        """启动 bridge 并把状态变化回调给 worker。"""
        ...

    async def stop(self) -> None:
        """停止 bridge 并释放调试资源。"""
        ...

    async def evaluate_js(self, expression: str, timeout: float = 5.0):
        """执行 Runtime.evaluate 并返回 CDP 响应。"""
        ...

    async def send_cdp_command(self, method: str, params: dict | None = None, timeout: float = 5.0):
        """发送任意 CDP 命令并返回响应。"""
        ...

    def on_cdp_event(self, method: str, callback: Callable[[dict], None]) -> None:
        """订阅指定 CDP 事件。"""
        ...

    def off_cdp_event(self, method: str, callback: Callable[[dict], None]) -> None:
        """取消订阅指定 CDP 事件。"""
        ...


class WorkerLogger:
    """Minimal logger adapter for the background bridge."""

    def _emit(self, *messages) -> None:
        """把 worker 日志安全输出到标准输出。"""
        print(" ".join(str(message) for message in messages), flush=True)

    def info(self, *messages) -> None:
        """输出普通信息日志。"""
        self._emit(*messages)

    def error(self, *messages) -> None:
        """输出错误日志。"""
        self._emit(*messages)

    def warn(self, *messages) -> None:
        """输出警告日志。"""
        self._emit(*messages)

    def main_debug(self, *messages) -> None:
        """忽略高频主调试日志，避免队列输出过载。"""
        return None

    def frida_debug(self, *messages) -> None:
        """忽略高频 Frida 调试日志，避免队列输出过载。"""
        return None


def normalize_devtools_proxy_message(message: str) -> str:
    """Normalize pause-on-exception messages to the safe default."""
    return normalize_proxy_message(message)


class BridgeOptions:
    """Small option object for the embedded debug engine."""

    def __init__(self, cdp_port: int, debug_port: int) -> None:
        """初始化嵌入式调试引擎端口配置。"""
        self.cdp_port = int(cdp_port)
        self.debug_port = int(debug_port)
        self.debug_main = False
        self.debug_frida = False
        self.scripts_dir = ""
        self.script_files: list[str] = []


class RealDebugEngineBridge:
    """Concrete bridge backed by the package-local debug engine."""

    def __init__(self) -> None:
        """初始化真实调试引擎引用。"""
        self.engine = None

    async def start(
        self,
        session: dict,
        debug_port: int,
        cdp_port: int,
        status_callback: Callable[[dict], None],
    ) -> None:
        """启动真实 DebugEngine 并注册状态回调。"""
        del session
        options = BridgeOptions(cdp_port=cdp_port, debug_port=debug_port)
        engine = DebugEngine(options, WorkerLogger())
        engine.on_status_change(lambda state: status_callback(dict(state)))
        try:
            await engine.start()
        except Exception:
            with contextlib.suppress(Exception):
                await engine.stop()
            raise
        self.engine = engine
        status_callback(dict(engine.status))

    async def stop(self) -> None:
        """停止真实 DebugEngine 并清空引用。"""
        engine = self.engine
        self.engine = None
        if engine is not None:
            await engine.stop()

    async def evaluate_js(self, expression: str, timeout: float = 5.0):
        """通过真实引擎执行 JavaScript 表达式。"""
        if self.engine is None:
            raise RuntimeError("debug engine not started")
        return await self.engine.evaluate_js(expression, timeout=timeout)

    async def send_cdp_command(self, method: str, params: dict | None = None, timeout: float = 5.0):
        """通过真实引擎发送 CDP 命令。"""
        if self.engine is None:
            raise RuntimeError("debug engine not started")
        return await self.engine.send_cdp_command(method, params=params, timeout=timeout)

    def on_cdp_event(self, method: str, callback: Callable[[dict], None]) -> None:
        """向真实引擎订阅 CDP 事件。"""
        if self.engine is None:
            return
        self.engine.on_cdp_event(method, callback)

    def off_cdp_event(self, method: str, callback: Callable[[dict], None]) -> None:
        """从真实引擎取消订阅 CDP 事件。"""
        if self.engine is None:
            return
        self.engine.off_cdp_event(method, callback)
