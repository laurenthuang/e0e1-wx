"""摘要：提供 package 内部可直接 await 的 MCP HTTP 服务启动协程，不解析命令行。"""

from __future__ import annotations

import asyncio
import multiprocessing as mp
import queue

from package.mcp_control.config import McpServerConfig
from package.mcp_control.worker import AsyncMcpServerWorker


async def run_http_server(config: McpServerConfig | None = None) -> None:
    """在当前进程运行 MCP HTTP 服务；调用方应放在独立 worker 中避免阻塞 UI。"""
    runtime_config = config or McpServerConfig()
    event_queue: mp.Queue = mp.Queue()
    command_queue: mp.Queue = mp.Queue()
    worker = AsyncMcpServerWorker(runtime_config, event_queue, command_queue)
    command_queue.put({"type": "start"})
    try:
        await worker.run()
    finally:
        while True:
            try:
                event_queue.get_nowait()
            except queue.Empty:
                break


def start_http_server_inside_process(config: McpServerConfig | None = None) -> None:
    """供 package 内部进程目标直接调用，统一交给 asyncio 调度。"""
    asyncio.run(run_http_server(config or McpServerConfig()))
