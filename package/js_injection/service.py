"""UI 侧 JS 文件目录扫描服务，负责和扫描 worker 通信。"""

from __future__ import annotations

import multiprocessing as mp
import queue

from PySide6.QtCore import QObject, QTimer, Signal

from package.js_injection.paths import tools_js_dir_path


class JsInjectionCatalogService(QObject):
    """管理 JS 文件扫描 worker，并向界面发布脚本列表。"""

    catalog_changed = Signal(list)
    catalog_error = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        """初始化扫描服务和 UI 事件轮询定时器。"""
        super().__init__(parent)
        self.event_queue: mp.Queue | None = None
        self.command_queue: mp.Queue | None = None
        self.process: mp.Process | None = None
        self._scripts: list[dict] = []
        self._last_imported_files: list[str] = []

        self.event_timer = QTimer(self)
        self.event_timer.timeout.connect(self.process_events)
        self.event_timer.start(100)

    def scripts(self) -> list[dict]:
        """返回当前缓存的 JS 脚本列表副本。"""
        return [dict(item) for item in self._scripts if isinstance(item, dict)]

    def ensure_worker_started(self) -> None:
        """按需启动独立扫描 worker 进程。"""
        if self.process is not None and self.process.is_alive():
            return
        from package.js_injection.worker import js_catalog_worker_main

        self.event_queue = mp.Queue()
        self.command_queue = mp.Queue()
        self.process = mp.Process(
            target=js_catalog_worker_main,
            args=(self.event_queue, self.command_queue, str(tools_js_dir_path())),
            daemon=True,
            name="js-injection-catalog-worker",
        )
        self.process.start()

    def refresh(
        self,
        imported_files: list[str] | tuple[str, ...] | None = None,
        runtime_toggle_overrides: dict[str, str] | None = None,
    ) -> None:
        """向扫描 worker 请求刷新脚本目录。"""
        if imported_files is not None:
            self._last_imported_files = [str(item) for item in imported_files]
        overrides = (
            {str(key): str(value) for key, value in runtime_toggle_overrides.items() if str(key or "").strip() and str(value or "").strip()}
            if isinstance(runtime_toggle_overrides, dict)
            else {}
        )
        self.ensure_worker_started()
        if self.command_queue is not None:
            self.command_queue.put(
                {
                    "type": "scan",
                    "imported_files": list(self._last_imported_files),
                    "runtime_toggle_overrides": overrides,
                }
            )

    def process_events(self) -> None:
        """轮询扫描 worker 事件并同步本地脚本缓存。"""
        if self.process is not None and not self.process.is_alive():
            self.process = None
            self.event_queue = None
            self.command_queue = None
            return
        if self.event_queue is None:
            return
        while True:
            try:
                event = self.event_queue.get_nowait()
            except queue.Empty:
                break
            self.handle_event(event)

    def handle_event(self, event: dict) -> None:
        """处理单条扫描 worker 事件。"""
        event_type = str(event.get("type") or "")
        if event_type == "catalog":
            scripts = event.get("scripts") if isinstance(event.get("scripts"), list) else []
            self._scripts = [dict(item) for item in scripts if isinstance(item, dict)]
            self.catalog_changed.emit(self.scripts())
            return
        if event_type == "catalog_error":
            self.catalog_error.emit(str(event.get("message") or "JS 文件扫描失败"))

    def shutdown(self, wait: bool = False) -> None:
        """停止扫描 worker 并释放队列引用。"""
        self.event_timer.stop()
        if self.command_queue is not None:
            self.command_queue.put({"type": "stop"})
        if wait:
            if self.process is not None and self.process.is_alive():
                self.process.join(timeout=1.0)
            if self.process is not None and self.process.is_alive():
                self.process.terminate()
                self.process.join(timeout=1.0)
        self.process = None
        self.event_queue = None
        self.command_queue = None
