"""摘要：UI 侧 MCP 控制服务，负责队列通信、状态缓存和 worker 生命周期。"""

from __future__ import annotations

import multiprocessing as mp
import queue

from PySide6.QtCore import QObject, QTimer, Signal

from package.mcp_control.config import McpServerConfig

MCP_EVENT_POLL_INTERVAL_MS = 120
MCP_EVENT_BATCH_LIMIT = 60


class McpControlService(QObject):
    """为主窗口提供 MCP 后台服务的异步启停接口。"""

    state_changed = Signal(dict)
    log_emitted = Signal(str)

    def __init__(self, parent: QObject | None = None, config: McpServerConfig | None = None) -> None:
        """初始化 UI 侧状态、进程安全队列和事件轮询定时器。"""
        super().__init__(parent)
        self.config = config or McpServerConfig()
        self.event_queue: mp.Queue | None = None
        self.command_queue: mp.Queue | None = None
        self.process: mp.Process | None = None
        self.state = self.config.state_payload(status="stopped", message="MCP 未启动")

        self.event_timer = QTimer(self)
        self.event_timer.timeout.connect(self.process_events)
        self.event_timer.start(MCP_EVENT_POLL_INTERVAL_MS)

    def snapshot(self) -> dict:
        """返回 UI 当前缓存的 MCP 状态副本。"""
        return dict(self.state)

    def ensure_worker_started(self) -> None:
        """按需启动独立 MCP worker 进程。"""
        if self.process is not None and self.process.is_alive():
            return
        from package.mcp_control.worker import mcp_worker_main

        self.event_queue = mp.Queue()
        self.command_queue = mp.Queue()
        self.process = mp.Process(
            target=mcp_worker_main,
            args=(self.config.to_payload(), self.event_queue, self.command_queue),
            daemon=False,
            name="mcp-control-async-worker",
        )
        self.process.start()

    def start_server(self) -> None:
        """向 MCP worker 发送后台启动命令。"""
        self.ensure_worker_started()
        if self.command_queue is not None:
            self.command_queue.put({"type": "start"})

    def stop_server(self) -> None:
        """向 MCP worker 发送停止命令。"""
        if self.command_queue is not None:
            self.command_queue.put({"type": "stop"})
            return
        self.handle_state(self.config.state_payload(status="stopped", message="MCP 未启动"))

    def request_status(self) -> None:
        """请求 MCP worker 回传当前状态。"""
        if self.command_queue is not None:
            self.command_queue.put({"type": "status"})
            return
        self.state_changed.emit(self.snapshot())

    def process_events(self) -> None:
        """非阻塞消费 worker 事件并同步 UI 状态。"""
        if self.process is not None and not self.process.is_alive():
            self.process = None
            self.event_queue = None
            self.command_queue = None
            if self.state.get("status") not in {"stopped", "failed"}:
                self.handle_state(self.config.state_payload(status="stopped", message="MCP worker 已退出"))
            return
        if self.event_queue is None:
            return
        for _index in range(MCP_EVENT_BATCH_LIMIT):
            try:
                event = self.event_queue.get_nowait()
            except queue.Empty:
                break
            self.handle_event(event)

    def handle_event(self, event: dict) -> None:
        """处理 MCP worker 发回的状态和日志事件。"""
        event_type = str(event.get("type") or "")
        if event_type == "state":
            state = event.get("state")
            if isinstance(state, dict):
                self.handle_state(state)
            return
        if event_type == "log":
            self.log_emitted.emit(str(event.get("message") or ""))

    def handle_state(self, state: dict) -> None:
        """更新本地状态缓存并通知界面刷新。"""
        self.state = dict(state)
        self.state_changed.emit(self.snapshot())

    def shutdown(self, wait: bool = False) -> None:
        """停止 MCP worker；默认不等待，避免阻塞关闭路径。"""
        self.event_timer.stop()
        if self.command_queue is not None:
            self.command_queue.put({"type": "shutdown"})
        if wait:
            if self.process is not None and self.process.is_alive():
                self.process.join(timeout=1.5)
            if self.process is not None and self.process.is_alive():
                self.process.terminate()
                self.process.join(timeout=1.0)
        self.process = None
        self.event_queue = None
        self.command_queue = None
