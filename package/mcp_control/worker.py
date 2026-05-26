"""摘要：在独立进程中运行 asyncio MCP HTTP 服务并响应启停命令。"""

from __future__ import annotations

import asyncio
import multiprocessing as mp
import queue
import sys
from pathlib import Path
from typing import Any

from package.mcp_control.config import McpServerConfig


class AsyncMcpServerWorker:
    """通过 multiprocessing 队列接收 UI 命令，并在子进程内托管 MCP 服务。"""

    def __init__(self, config: McpServerConfig, event_queue: mp.Queue, command_queue: mp.Queue) -> None:
        """初始化 MCP worker 的配置、事件队列和命令队列。"""
        self.config = config
        self.event_queue = event_queue
        self.command_queue = command_queue
        self.running = True
        self.server: Any | None = None
        self.server_task: asyncio.Task | None = None

    async def run(self) -> None:
        """运行 worker 主循环，确保单任务异常不会杀死主程序。"""
        self.emit_state("stopped", "MCP 未启动")
        try:
            while self.running:
                await self.process_commands()
                await self.check_server_task()
                await asyncio.sleep(0.1)
        except Exception as exc:
            self.emit_state("failed", f"MCP worker 异常：{exc}", last_error=str(exc))
        finally:
            await self.stop_server("MCP worker 已退出")

    async def process_commands(self) -> None:
        """处理 UI 发送的 start、stop、status 和 shutdown 命令。"""
        while True:
            try:
                command = self.command_queue.get_nowait()
            except queue.Empty:
                break

            command_type = str(command.get("type") or "")
            if command_type == "start":
                await self.start_server()
            elif command_type == "stop":
                await self.stop_server("MCP 已停止")
            elif command_type == "status":
                self.emit_current_state()
            elif command_type == "shutdown":
                self.running = False
                await self.stop_server("MCP 已停止")
                break

    async def start_server(self) -> None:
        """异步启动 MCP HTTP 服务，重复启动时只刷新状态。"""
        if self.server_task is not None and not self.server_task.done():
            self.emit_state("running", "MCP 已运行")
            return

        root = self.config.resolved_project_root()
        ready = await asyncio.to_thread(self.reference_project_ready, root)
        if not ready:
            message = f"MCP 内置项目不存在或缺少 package/mcp_control/local_app.py：{root}"
            self.emit_state("failed", message, last_error=message)
            return

        self.emit_state("starting", "MCP 正在后台启动")
        try:
            self.prepare_reference_imports(root)
            server = await self.build_uvicorn_server()
            self.server = server
            self.server_task = asyncio.create_task(server.serve())
            await self.wait_until_started()
        except Exception as exc:
            self.server = None
            self.server_task = None
            self.emit_state("failed", f"MCP 启动失败：{exc}", last_error=str(exc))

    async def wait_until_started(self) -> None:
        """等待 uvicorn 完成监听，失败时把异常转成 UI 状态事件。"""
        if self.server is None or self.server_task is None:
            self.emit_state("failed", "MCP 服务对象未创建", last_error="server missing")
            return

        for _index in range(80):
            if self.server_task.done():
                await self.raise_finished_server_error()
                return
            if bool(getattr(self.server, "started", False)):
                self.emit_state("running", f"MCP 已启动：{self.config.endpoint_url()}")
                return
            await asyncio.sleep(0.05)
        self.emit_state("starting", f"MCP 启动中：{self.config.endpoint_url()}")

    async def raise_finished_server_error(self) -> None:
        """读取提前结束的 uvicorn 任务异常并抛给启动流程。"""
        if self.server_task is None:
            raise RuntimeError("MCP 服务任务不存在")
        try:
            await self.server_task
        except Exception as exc:
            raise RuntimeError(str(exc)) from exc
        raise RuntimeError("MCP 服务已退出")

    async def stop_server(self, message: str) -> None:
        """异步停止 MCP HTTP 服务，并清理服务任务引用。"""
        if self.server is None and self.server_task is None:
            self.emit_state("stopped", message)
            return

        self.emit_state("stopping", "MCP 正在停止")
        server = self.server
        task = self.server_task
        if server is not None:
            server.should_exit = True
        if task is not None:
            try:
                await asyncio.wait_for(task, timeout=5.0)
            except asyncio.TimeoutError:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            except Exception as exc:
                self.emit_log(f"MCP 停止时收到异常：{exc}")
        self.server = None
        self.server_task = None
        self.emit_state("stopped", message)

    async def check_server_task(self) -> None:
        """检查 MCP 服务任务是否异常退出，并隔离错误。"""
        if self.server_task is None or not self.server_task.done():
            return
        try:
            await self.server_task
        except Exception as exc:
            self.emit_state("failed", f"MCP 已退出：{exc}", last_error=str(exc))
        else:
            self.emit_state("stopped", "MCP 已退出")
        finally:
            self.server = None
            self.server_task = None

    async def build_uvicorn_server(self):
        """按 package 内置逻辑构建本机 Streamable HTTP MCP 服务。"""
        import uvicorn
        from starlette.requests import Request
        from starlette.responses import PlainTextResponse
        from starlette.routing import Route

        from package.mcp_control.local_app import create_mcp_app
        from package.mcp_control.token_middleware import TokenMiddleware

        mcp = create_mcp_app()
        app = mcp.streamable_http_app()

        async def root(_request: Request) -> PlainTextResponse:
            """返回当前 MCP 地址和 CLI 添加命令。"""
            install_commands = self.config.install_commands()
            delete_commands = self.config.delete_commands()
            return PlainTextResponse(
                "\n".join(
                    [
                        "e0e1-wx-gui package-local MCP",
                        "",
                        "Streamable HTTP MCP endpoint:",
                        self.config.endpoint_url(),
                        "",
                        "Claude Code add:",
                        install_commands["claude"],
                        "Claude Code remove:",
                        delete_commands["claude"],
                        "",
                        "Codex CLI add:",
                        install_commands["codex"],
                        "Codex CLI remove:",
                        delete_commands["codex"],
                    ]
                )
            )

        app.routes.append(Route("/", endpoint=root, methods=["GET"]))
        secured_app = TokenMiddleware(app, self.config.token)
        return uvicorn.Server(
            uvicorn.Config(
                secured_app,
                host=self.config.host,
                port=int(self.config.port),
                log_level="info",
                log_config=None,
            )
        )

    def emit_current_state(self) -> None:
        """把当前 worker 状态发送给 UI。"""
        if self.server_task is not None and not self.server_task.done():
            status = "running" if bool(getattr(self.server, "started", False)) else "starting"
            self.emit_state(status, f"MCP 已启动：{self.config.endpoint_url()}")
            return
        self.emit_state("stopped", "MCP 未启动")

    def emit_state(self, status: str, message: str, *, last_error: str = "") -> None:
        """发送状态事件到 UI 进程，队列满时静默丢弃本次状态。"""
        payload = self.config.state_payload(status=status, message=message, pid=None, last_error=last_error)
        self.emit({"type": "state", "state": payload})

    def emit_log(self, message: str) -> None:
        """发送运行日志到 UI 进程。"""
        self.emit({"type": "log", "message": str(message)})

    def emit(self, event: dict) -> None:
        """使用进程安全队列向 UI 进程发布事件。"""
        try:
            self.event_queue.put_nowait(dict(event))
        except queue.Full:
            return

    @staticmethod
    def reference_project_ready(root: Path) -> bool:
        """检查当前项目是否包含内置 MCP 应用文件。"""
        return (root / "package" / "mcp_control" / "local_app.py").exists()

    @staticmethod
    def prepare_reference_imports(root: Path) -> None:
        """把当前项目根目录加入 worker 的 import 路径。"""
        src_path = str(root)
        if src_path not in sys.path:
            sys.path.insert(0, src_path)


def mcp_worker_main(config_payload: dict, event_queue: mp.Queue, command_queue: mp.Queue) -> None:
    """multiprocessing 子进程入口，运行 MCP asyncio worker。"""
    config = McpServerConfig.from_payload(config_payload)
    asyncio.run(AsyncMcpServerWorker(config, event_queue, command_queue).run())
