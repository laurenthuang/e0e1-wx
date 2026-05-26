"""负责 JS 文件目录扫描的独立 asyncio + multiprocessing worker。"""

from __future__ import annotations

import asyncio
import multiprocessing as mp
import queue
from pathlib import Path

from package.js_injection.catalog import scan_js_catalog


class AsyncJsCatalogWorker:
    """在独立进程中处理 JS 文件扫描，避免 UI 主线程执行文件 IO。"""

    def __init__(self, event_queue: mp.Queue, command_queue: mp.Queue, tools_dir: str) -> None:
        """初始化事件队列、命令队列和默认扫描目录。"""
        self.event_queue = event_queue
        self.command_queue = command_queue
        self.tools_dir = Path(tools_dir)
        self.running = True

    async def run(self) -> None:
        """运行命令循环并隔离单次扫描异常。"""
        try:
            while self.running:
                await self.process_commands()
                await asyncio.sleep(0.05)
        except Exception as exc:
            self.event_queue.put({"type": "catalog_error", "message": f"JS 扫描 worker 异常：{exc}"})

    async def process_commands(self) -> None:
        """非阻塞消费命令，只执行最新一次扫描请求。"""
        latest_imported_files: list[str] | None = None
        latest_runtime_toggle_overrides: dict[str, str] | None = None
        while True:
            try:
                command = self.command_queue.get_nowait()
            except queue.Empty:
                break
            command_type = str(command.get("type") or "")
            if command_type == "stop":
                self.running = False
                break
            if command_type == "scan":
                imported = command.get("imported_files")
                overrides = command.get("runtime_toggle_overrides")
                latest_imported_files = [str(item) for item in imported] if isinstance(imported, list) else []
                latest_runtime_toggle_overrides = (
                    {str(key): str(value) for key, value in overrides.items() if str(key or "").strip() and str(value or "").strip()}
                    if isinstance(overrides, dict)
                    else {}
                )

        if latest_imported_files is None:
            return
        try:
            scripts = await scan_js_catalog(
                self.tools_dir,
                latest_imported_files,
                runtime_toggle_overrides=latest_runtime_toggle_overrides or {},
            )
            self.event_queue.put({"type": "catalog", "scripts": scripts})
        except Exception as exc:
            self.event_queue.put({"type": "catalog_error", "message": f"JS 文件扫描失败：{exc}"})


def js_catalog_worker_main(event_queue: mp.Queue, command_queue: mp.Queue, tools_dir: str) -> None:
    """JS 文件扫描子进程入口。"""
    asyncio.run(AsyncJsCatalogWorker(event_queue, command_queue, tools_dir).run())
