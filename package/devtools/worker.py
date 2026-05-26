"""共享 DevTools 后台 worker，负责调试会话、路由、跳转、云审计和 JS 注入任务隔离。"""

from __future__ import annotations

import asyncio
import contextlib
import multiprocessing as mp
import queue
import socket
from typing import Awaitable, Callable

from package.applet_debug import copy_debug_toggle_state, default_debug_toggle_state
from package.applet_debug.runtime import DebugToggleRuntime
from package.applet_routes.action_policy import (
    build_relaunch_fallback_message,
    build_route_action_message,
    is_tabbar_route,
    resolve_route_action,
    should_fallback_to_relaunch,
)
from package.applet_routes.navigator import MiniProgramRouteNavigator
from package.applet_routes.state import copy_route_state, default_route_state
from package.miniapp_jump.navigator import MiniAppJumpNavigator
from package.miniapp_jump.state import copy_miniapp_jump_state, default_miniapp_jump_state
from package.config.defaults import (
    DEFAULT_DEVTOOLS_CDP_PORT,
    DEFAULT_MINIAPP_DEBUG_PORT,
    normalize_cloud_call_timeout,
    normalize_devtools_port,
    normalize_route_traverse_interval,
)
from package.cloud_audit import CloudAuditRuntime, copy_cloud_state, default_cloud_state, normalize_cloud_call_record
from package.cloud_audit.runtime import cloud_call_transport_timeout
from package.devtools.bridge import EngineBridge, RealDebugEngineBridge
from package.devtools.constants import CDP_PORT_END, CDP_PORT_START
from package.devtools.js_injection_recovery import build_auto_restore_candidates
from package.devtools.state import build_devtools_link, copy_state, default_state
from package.js_injection.models import is_runtime_toggle_script, normalize_script_mode
from package.js_injection.runtime import inject_js_file
from package.js_injection.runtime_toggle import disable_runtime_js_file, enable_runtime_js_file

MINIAPP_RESTART_HINT = "如小程序已提前打开，请重启小程序后再试"
ROUTE_ACTION_LABELS = {
    "switch_tab": "切换标签页",
    "navigate_to": "打开新页面",
    "redirect_to": "替换当前页",
    "relaunch": "重启到页面",
    "navigate_back": "返回上一页",
}
DEBUG_TOGGLE_ACTION_LABELS = {
    "detect": "检测调试状态",
    "enable": "开启调试",
    "disable": "关闭调试",
}
TRANSIENT_MINIAPP_DISCONNECT_MARKERS = (
    "miniapp disconnected",
    "no miniapp client connected",
    "等待小程序回连",
    "小程序未回连",
)


def find_available_cdp_port(start: int = CDP_PORT_START) -> int:
    """查找首个可用的 CDP 代理端口。"""
    for port in range(int(start), CDP_PORT_END + 1):
        with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError("No available CDP port found")


def is_address_in_use_error(exc: BaseException) -> bool:
    """判断异常是否属于端口占用错误，供启动阶段决定是否继续重试。"""
    error_number = getattr(exc, "errno", None)
    if error_number in {48, 98, 10048}:
        return True
    message = str(exc or "").lower()
    return any(
        marker in message
        for marker in (
            "10048",
            "address already in use",
            "only one usage of each socket address",
            "只允许使用一次",
            "端口占用",
        )
    )


class AsyncDevtoolsWorker:
    """支持调试与路由切换的单会话异步 worker。"""

    def __init__(
        self,
        event_queue: mp.Queue,
        command_queue: mp.Queue,
        bridge_factory: Callable[[], EngineBridge] | None = None,
        navigator_factory: Callable[[EngineBridge], MiniProgramRouteNavigator] | None = None,
        jump_navigator_factory: Callable[[EngineBridge], MiniAppJumpNavigator] | None = None,
        debug_runtime_factory: Callable[[EngineBridge, MiniProgramRouteNavigator], DebugToggleRuntime] | None = None,
        cdp_port_finder: Callable[[int], int] | None = None,
        poll_interval: float = 0.03,
        miniapp_ready_timeout: float = 15.0,
        traverse_route_delay: float = 2.0,
        sleep_func: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        """初始化 worker 队列、依赖工厂、任务表和默认状态。"""
        self.event_queue = event_queue
        self.command_queue = command_queue
        self.bridge_factory = bridge_factory or RealDebugEngineBridge
        self.navigator_factory = navigator_factory or MiniProgramRouteNavigator
        self.jump_navigator_factory = jump_navigator_factory or MiniAppJumpNavigator
        self.debug_runtime_factory = debug_runtime_factory or DebugToggleRuntime
        self.cdp_port_finder = cdp_port_finder or find_available_cdp_port
        self.poll_interval = float(poll_interval)
        self.miniapp_ready_timeout = float(miniapp_ready_timeout)
        self.traverse_route_delay = normalize_route_traverse_interval(traverse_route_delay)
        self.sleep_func = sleep_func or asyncio.sleep
        self.running = True
        self.bridge: EngineBridge | None = None
        self.route_navigator: MiniProgramRouteNavigator | None = None
        self.transition_task: asyncio.Task | None = None
        self.route_tasks: dict[int, asyncio.Task] = {}
        self.jump_tasks: dict[int, asyncio.Task] = {}
        self.invalidated_jump_tasks: set[asyncio.Task] = set()
        self.debug_tasks: dict[int, asyncio.Task] = {}
        self.debug_states: dict[int, dict] = {}
        self.jump_states: dict[int, dict] = {}
        self.route_states: dict[int, dict] = {}
        self.cloud_runtime: CloudAuditRuntime | None = None
        self.cloud_operation_task: asyncio.Task | None = None
        self.cloud_poll_task: asyncio.Task | None = None
        self.js_injection_tasks: dict[tuple[int, str], asyncio.Task] = {}
        self.js_injection_states: dict[int, dict[str, dict]] = {}
        self.injected_js_signatures: dict[str, set[tuple[str, str]]] = {}
        self.cloud_state = default_cloud_state()
        self.cloud_calls: list[dict] = []
        self.cloud_call_history: list[dict] = []
        self.state = default_state()

    async def run(self) -> None:
        """持续运行 worker 主循环，并隔离调试生命周期异常。"""
        self.state = default_state(worker_alive=True, message="Devtools worker 已就绪")
        self.cloud_state = default_cloud_state(worker_alive=True, message="云函数捕获 worker 已就绪")
        self.emit_state()
        self.emit_cloud_state()
        try:
            while self.running:
                await self.process_commands()
                await asyncio.sleep(self.poll_interval)
        except Exception as exc:
            self.state.update(
                {
                    "status": "failed",
                    "message": f"Devtools worker 异常：{exc}",
                    "error": str(exc),
                }
            )
            self.emit_state()
        finally:
            await self.cancel_transition()
            await self.cancel_all_debug_tasks()
            await self.cancel_all_jump_tasks()
            await self.cancel_all_js_injection_tasks()
            await self.cancel_all_route_tasks()
            with contextlib.suppress(Exception):
                await self.stop_bridge()
            self.state = default_state()
            self.emit_state()
            self.cloud_state = default_cloud_state()
            self.emit_cloud_state()

    def emit(self, event: dict) -> None:
        """向界面侧发送通用 worker 事件。"""
        self.event_queue.put(event)

    def emit_state(self) -> None:
        """向界面侧发布最新的全局调试状态快照。"""
        self.event_queue.put({"type": "devtools_state", "state": copy_state(self.state)})

    def emit_route_state(self, record_id: int) -> None:
        """向界面侧发布指定记录的最新路由状态。"""
        self.event_queue.put(
            {
                "type": "route_state",
                "record_id": int(record_id or 0),
                "state": copy_route_state(self.route_states.get(int(record_id or 0), {})),
            }
        )

    def emit_debug_state(self, record_id: int) -> None:
        """向界面侧发布指定记录的调试开关状态。"""
        self.event_queue.put(
            {
                "type": "debug_toggle_state",
                "record_id": int(record_id or 0),
                "state": copy_debug_toggle_state(self.debug_states.get(int(record_id or 0), {})),
            }
        )

    def emit_jump_state(self, record_id: int) -> None:
        """向界面层发布指定记录的跨小程序跳转状态快照。"""
        self.event_queue.put(
            {
                "type": "miniapp_jump_state",
                "record_id": int(record_id or 0),
                "state": copy_miniapp_jump_state(self.jump_states.get(int(record_id or 0), {})),
            }
        )

    def emit_js_injection_state(self, record_id: int, script_id: str) -> None:
        """向界面侧发布指定记录和脚本的 JS 注入状态。"""
        states = self.js_injection_states.get(int(record_id or 0), {})
        state = dict(states.get(str(script_id or ""), {})) if isinstance(states, dict) else {}
        self.event_queue.put(
            {
                "type": "js_injection_state",
                "record_id": int(record_id or 0),
                "script_id": str(script_id or ""),
                "state": state,
            }
        )

    def emit_debug_log(self, command: dict, *, level: str, stage: str, action: str, message: str) -> None:
        """向界面侧发布调试开关链路上的结构化日志。"""
        session = self.build_session(command)
        self.emit(
            {
                "type": "debug_toggle_log",
                "record_id": int(session["record_id"] or 0),
                "owner_key": session["owner_key"],
                "display_name": session["display_name"],
                "level": str(level or "INFO").upper(),
                "stage": str(stage or "").strip(),
                "action": str(action or "").strip(),
                "message": str(message or "").strip(),
            }
        )

    async def process_commands(self) -> None:
        """以非阻塞方式消费界面层发来的命令。"""
        while True:
            try:
                command = self.command_queue.get_nowait()
            except queue.Empty:
                return
            await self.handle_command(command)

    async def handle_command(self, command: dict) -> None:
        """统一分发单条命令，供真实队列轮询和测试场景共同复用。"""
        command_type = str(command.get("type") or "")
        record_id = int(command.get("record_id") or 0)
        if command_type == "shutdown":
            self.running = False
            await self.cancel_transition()
            await self.cancel_all_debug_tasks()
            await self.cancel_all_jump_tasks()
            await self.cancel_all_js_injection_tasks()
            await self.cancel_cloud_operation()
            await self.cancel_all_route_tasks()
            with contextlib.suppress(Exception):
                await self.stop_bridge()
            return
        if command_type == "query_state":
            self.emit_state()
            return
        if command_type == "stop_session":
            await self.schedule_transition(self.stop_transition())
            return
        if command_type == "start_session":
            await self.schedule_transition(self.start_transition(command))
            return
        if command_type == "detect_debug_toggle":
            await self.schedule_debug_task(record_id, self.detect_debug_toggle(command))
            return
        if command_type == "set_debug_toggle":
            await self.schedule_debug_task(record_id, self.set_debug_toggle(command))
            return
        if command_type == "cancel_debug_toggle":
            await self.cancel_debug_task(record_id)
            return
        if command_type == "jump_to_mini_program":
            await self.schedule_jump_task(record_id, self.jump_to_mini_program(command))
            return
        if command_type == "cancel_miniapp_jump":
            await self.cancel_jump_task(record_id)
            return
        if command_type == "start_cloud_audit":
            await self.schedule_cloud_operation(self.start_cloud_audit(command))
            return
        if command_type == "stop_cloud_audit":
            await self.schedule_cloud_operation(self.stop_cloud_audit())
            return
        if command_type == "clear_cloud_audit":
            await self.clear_cloud_audit()
            return
        if command_type == "call_cloud_function":
            await self.schedule_cloud_operation(self.call_cloud_function(command))
            return
        if command_type == "scan_cloud_static":
            await self.schedule_cloud_operation(self.scan_cloud_static(command))
            return
        if command_type == "inject_js_script":
            script = command.get("script") if isinstance(command.get("script"), dict) else {}
            script_id = str(script.get("id") or command.get("script_id") or "")
            await self.schedule_js_injection_task(record_id, script_id, self.inject_js_script(command))
            return
        if command_type == "enable_runtime_js_script":
            script = command.get("script") if isinstance(command.get("script"), dict) else {}
            script_id = str(script.get("id") or command.get("script_id") or "")
            await self.schedule_js_injection_task(record_id, script_id, self.enable_runtime_js_script(command))
            return
        if command_type == "disable_runtime_js_script":
            script = command.get("script") if isinstance(command.get("script"), dict) else {}
            script_id = str(script.get("id") or command.get("script_id") or "")
            await self.schedule_js_injection_task(record_id, script_id, self.disable_runtime_js_script(command))
            return
        if command_type == "set_runtime_toggle_auto_restore":
            self.set_runtime_toggle_auto_restore(command)
            return
        if command_type == "cancel_js_injection":
            script_id = str(command.get("script_id") or "")
            await self.cancel_js_injection_task(record_id, script_id)
            return
        if command_type == "cancel_route_tasks":
            await self.cancel_route_task(record_id)
            return
        if command_type == "attach_route":
            await self.schedule_route_task(record_id, self.attach_route(command))
            return
        if command_type == "refresh_routes":
            await self.schedule_route_task(record_id, self.refresh_routes(command))
            return
        if command_type == "execute_route_action":
            await self.schedule_route_task(record_id, self.execute_route_action(command))
            return
        if command_type == "navigate_back_route":
            await self.schedule_route_task(record_id, self.navigate_back_route(command))
            return
        if command_type == "traverse_routes":
            await self.schedule_route_task(record_id, self.traverse_routes(command))
            return
        if command_type == "toggle_route_guard":
            await self.schedule_route_task(record_id, self.toggle_route_guard(command))

    async def schedule_transition(self, transition_coro) -> None:
        """用新的调试切换任务替换当前仍在执行的切换任务。"""
        await self.cancel_transition()
        self.transition_task = asyncio.create_task(transition_coro)

    async def cancel_transition(self) -> None:
        """取消当前尚未结束的调试切换任务。"""
        task = self.transition_task
        self.transition_task = None
        if task is None:
            return
        if not task.done():
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task

    async def wait_for_transition(self) -> None:
        """等待当前调试切换任务执行完成。"""
        task = self.transition_task
        if task is None:
            return
        try:
            await task
        finally:
            if self.transition_task is task:
                self.transition_task = None

    async def schedule_debug_task(self, record_id: int, debug_coro) -> None:
        """为指定记录替换掉仍在执行中的调试开关任务。"""
        await self.cancel_debug_task(record_id)
        self.debug_tasks[record_id] = asyncio.create_task(self.run_debug_task(record_id, debug_coro))
        await asyncio.sleep(0)

    async def run_debug_task(self, record_id: int, debug_coro) -> None:
        """运行单个调试开关任务，并确保取消后不会残留忙碌态。"""
        try:
            await debug_coro
        except asyncio.CancelledError:
            self.mark_debug_task_cancelled(record_id)
            raise

    def mark_debug_task_cancelled(self, record_id: int) -> None:
        """把被取消的调试开关任务回写为失败状态，允许页面重试。"""
        state = self.debug_states.get(int(record_id or 0))
        if not isinstance(state, dict):
            return
        if str(state.get("status") or "") not in {"idle", "detecting", "enabling", "disabling"}:
            return
        state.update(
            {
                "status": "failed",
                "message": "调试任务已取消，可重新执行",
                "error": "debug task cancelled",
            }
        )
        self.emit_debug_state(record_id)

    async def cancel_debug_task(self, record_id: int) -> None:
        """取消指定记录当前正在执行的调试开关任务。"""
        task = self.debug_tasks.pop(int(record_id or 0), None)
        if task is None:
            return
        if not task.done():
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
        self.mark_debug_task_cancelled(record_id)

    async def cancel_all_debug_tasks(self) -> None:
        """在 worker 退出前取消全部未完成的调试开关任务。"""
        for record_id in list(self.debug_tasks):
            await self.cancel_debug_task(record_id)

    async def wait_for_debug_task(self, record_id: int) -> None:
        """等待指定记录的调试开关任务完成，供测试复用。"""
        task = self.debug_tasks.get(int(record_id or 0))
        if task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def schedule_jump_task(self, record_id: int, jump_coro) -> None:
        """为指定记录替换仍在执行中的小程序跳转任务。"""
        await self.cancel_jump_task(record_id)
        self.jump_tasks[record_id] = asyncio.create_task(self.run_jump_task(record_id, jump_coro))
        await asyncio.sleep(0)

    async def run_jump_task(self, record_id: int, jump_coro) -> None:
        """运行单个跨小程序跳转任务，并确保取消后会及时标记。"""
        try:
            await jump_coro
        except asyncio.CancelledError:
            self.mark_jump_task_cancelled(record_id)
            raise

    @staticmethod
    def normalize_jump_path(path: str) -> str:
        """统一归一化跨小程序跳转路径，避免状态展示与实际发送不一致。"""
        return str(path or "").strip().lstrip("/")

    def ensure_jump_state(
        self,
        command: dict,
        *,
        status: str,
        message: str,
        error: str,
        target_appid: str,
        target_path: str,
        last_action: str,
    ) -> dict:
        """确保指定记录始终有一份可更新的跳转状态缓存。"""
        session = self.build_session(command)
        record_id = int(session["record_id"] or 0)
        state = self.jump_states.setdefault(
            record_id,
            default_miniapp_jump_state(
                record_id=record_id,
                owner_key=session["owner_key"],
                display_name=session["display_name"],
                worker_alive=True,
            ),
        )
        state.update(
            {
                "record_id": record_id,
                "owner_key": session["owner_key"],
                "display_name": session["display_name"],
                "worker_alive": True,
                "status": status,
                "target_appid": target_appid,
                "target_path": self.normalize_jump_path(target_path),
                "last_action": last_action,
                "message": message,
                "error": error,
            }
        )
        return state

    def mark_jump_task_cancelled(self, record_id: int) -> None:
        """把被取消的跳转任务标记为已取消状态。"""
        state = self.jump_states.get(int(record_id or 0))
        if not isinstance(state, dict):
            return
        if str(state.get("status") or "") != "executing":
            return
        state.update(
            {
                "status": "cancelled",
                "target_path": str(state.get("target_path") or ""),
                "message": "小程序跳转任务已取消",
                "error": "miniapp jump task cancelled",
            }
        )
        self.emit_jump_state(record_id)

    def invalidate_jump_task(self, task: asyncio.Task | None) -> None:
        """把已脱离当前记录管理的跳转任务标记为失效，避免晚到结果覆盖终态。"""
        if task is None:
            return
        self.invalidated_jump_tasks.add(task)
        task.add_done_callback(self.discard_invalidated_jump_task)

    def discard_invalidated_jump_task(self, task: asyncio.Task) -> None:
        """在跳转任务真正结束后移除失效标记，避免集合持续增长。"""
        self.invalidated_jump_tasks.discard(task)

    def is_jump_task_invalidated(self, task: asyncio.Task | None) -> bool:
        """判断当前跳转任务是否已经被上层生命周期主动作废。"""
        return task is not None and task in self.invalidated_jump_tasks

    async def cancel_jump_task(self, record_id: int, *, cancel_transition: bool = True, wait: bool = True) -> None:
        """取消指定记录当前正在执行的跳转任务。"""
        record_id = int(record_id or 0)
        task = self.jump_tasks.pop(record_id, None)
        if task is None:
            return
        self.invalidate_jump_task(task)
        if not task.done():
            task.cancel()
        if cancel_transition and int(self.state.get("record_id") or 0) == record_id and self.transition_task is not None:
            await self.cancel_transition()
        if wait:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

    async def cancel_all_jump_tasks(self, *, cancel_transition: bool = True, wait: bool = True) -> None:
        """在 worker 退出前取消全部未完成的小程序跳转任务。"""
        for record_id in list(self.jump_tasks):
            await self.cancel_jump_task(record_id, cancel_transition=cancel_transition, wait=wait)

    async def stop_managed_jump_tasks(self, message: str) -> None:
        """在会话停止或切换前统一冻结所有跳转状态并异步取消任务。"""
        self.mark_jump_states_stopped(message)
        await self.cancel_all_jump_tasks(cancel_transition=False, wait=False)

    async def wait_for_jump_task(self, record_id: int) -> None:
        """等待指定记录的跳转任务完成，供测试复用。"""
        task = self.jump_tasks.get(int(record_id or 0))
        if task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def schedule_js_injection_task(self, record_id: int, script_id: str, injection_coro) -> None:
        """为指定记录和脚本替换仍在执行中的 JS 注入任务。"""
        key = (int(record_id or 0), str(script_id or ""))
        await self.cancel_js_injection_task(*key)
        self.js_injection_tasks[key] = asyncio.create_task(self.run_js_injection_task(key, injection_coro))
        await asyncio.sleep(0)

    async def run_js_injection_task(self, key: tuple[int, str], injection_coro) -> None:
        """运行单个 JS 注入任务，并确保取消时状态可恢复。"""
        try:
            await injection_coro
        except asyncio.CancelledError:
            self.mark_js_injection_task_cancelled(key[0], key[1])
            raise

    def mark_js_injection_task_cancelled(self, record_id: int, script_id: str) -> None:
        """把被取消的 JS 注入任务标记为失败，方便用户重试。"""
        state = self.js_injection_states.get(int(record_id or 0), {}).get(str(script_id or ""))
        if not isinstance(state, dict):
            return
        status = str(state.get("status") or "")
        if status not in {"injecting", "enabling", "disabling"}:
            return
        message = "长期脚本任务已取消" if status in {"enabling", "disabling"} else "JS 注入任务已取消"
        state.update({"status": "failed", "enabled": False, "message": message, "error": "js injection task cancelled"})
        self.emit_js_injection_state(record_id, script_id)

    async def cancel_js_injection_task(self, record_id: int, script_id: str) -> None:
        """取消指定记录和脚本的 JS 注入任务。"""
        task = self.js_injection_tasks.pop((int(record_id or 0), str(script_id or "")), None)
        if task is None:
            return
        if not task.done():
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task

    async def cancel_all_js_injection_tasks(self) -> None:
        """取消所有尚未完成的 JS 注入任务。"""
        for record_id, script_id in list(self.js_injection_tasks):
            await self.cancel_js_injection_task(record_id, script_id)

    def ensure_js_injection_state(self, command: dict, *, status: str, message: str, error: str) -> dict:
        """确保指定记录和脚本始终有一份可更新的 JS 注入状态。"""
        session = self.build_session(command)
        record_id = int(session["record_id"] or 0)
        script = command.get("script") if isinstance(command.get("script"), dict) else {}
        script_id = str(script.get("id") or command.get("script_id") or "").strip()
        script_name = str(script.get("name") or "JS文件").strip()
        state = self.js_injection_states.setdefault(record_id, {}).setdefault(script_id, {})
        mode = normalize_script_mode(script.get("mode"))
        miniapp_epoch = int(self.state.get("miniapp_epoch") or state.get("miniapp_epoch") or 0)
        state.update(
            {
                "record_id": record_id,
                "owner_key": session["owner_key"],
                "display_name": session["display_name"],
                "script_id": script_id,
                "script_name": script_name,
                "path": str(script.get("path") or ""),
                "signature": str(script.get("signature") or ""),
                "automatic": bool(command.get("automatic")),
                "auto_restore": bool(command.get("auto_restore", state.get("auto_restore"))),
                "worker_alive": True,
                "mode": mode,
                "status": status,
                "enabled": bool(state.get("enabled")),
                "message": message,
                "error": error,
                "log": "",
                "controller_key": str(state.get("controller_key") or ""),
                "persistent_identifier": str(state.get("persistent_identifier") or ""),
                "miniapp_epoch": miniapp_epoch,
                "script": dict(script),
            }
        )
        return state

    def set_runtime_toggle_auto_restore(self, command: dict) -> None:
        """更新指定长期脚本的自动恢复资格。"""
        script = command.get("script") if isinstance(command.get("script"), dict) else {}
        script_id = str(script.get("id") or command.get("script_id") or "").strip()
        record_id = int(command.get("record_id") or 0)
        state = self.ensure_js_injection_state(command, status="disabled", message="未注入", error="")
        state.update({"script": dict(script), "auto_restore": bool(command.get("enabled"))})
        self.emit_js_injection_state(record_id, script_id)

    async def inject_js_script(self, command: dict) -> None:
        """在当前小程序 Runtime 中注入指定 JS 文件。"""
        script = command.get("script") if isinstance(command.get("script"), dict) else {}
        script_id = str(script.get("id") or command.get("script_id") or "").strip()
        record_id = int(command.get("record_id") or 0)
        if is_runtime_toggle_script(script):
            state = self.ensure_js_injection_state(
                command,
                status="failed",
                message="长期脚本请使用启用/取消注入",
                error="runtime toggle script requires enable/disable",
            )
            state.update({"enabled": False})
            self.emit_js_injection_state(record_id, script_id)
            return
        state = self.ensure_js_injection_state(command, status="injecting", message="正在注入", error="")
        self.emit_js_injection_state(record_id, script_id)
        try:
            await self.ensure_route_session(command)
            if self.bridge is None:
                raise RuntimeError("devtools bridge unavailable")
            owner_key = str(self.state.get("owner_key") or command.get("owner_key") or "")
            automatic = bool(command.get("automatic"))
            injected_keys = self.injected_js_signatures.setdefault(owner_key, set()) if automatic else set()
            result = await inject_js_file(self.bridge, script, injected_keys, automatic=automatic)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            state.update({"status": "failed", "message": "注入失败", "error": str(exc)})
            self.emit_js_injection_state(record_id, script_id)
            return
        skipped = bool(result.get("skipped"))
        state.update(
            {
                "status": "success",
                "enabled": False,
                "message": "已注入，跳过重复注入" if skipped else "注入成功",
                "error": "",
                "log": str(result.get("log") or "").strip(),
            }
        )
        self.emit_js_injection_state(record_id, script_id)

    async def enable_runtime_js_script(self, command: dict) -> None:
        """在当前小程序 runtime 中启用支持长期控制的 JS 脚本。"""
        script = command.get("script") if isinstance(command.get("script"), dict) else {}
        script_id = str(script.get("id") or command.get("script_id") or "").strip()
        record_id = int(command.get("record_id") or 0)
        if not is_runtime_toggle_script(script):
            state = self.ensure_js_injection_state(
                command,
                status="failed",
                message="该脚本不是长期脚本",
                error="script is not runtime toggle",
            )
            state.update({"enabled": False})
            self.emit_js_injection_state(record_id, script_id)
            return
        state = self.ensure_js_injection_state(command, status="enabling", message="正在启用", error="")
        state.update({"enabled": False, "miniapp_epoch": int(self.state.get("miniapp_epoch") or state.get("miniapp_epoch") or 0)})
        self.emit_js_injection_state(record_id, script_id)
        try:
            await self.ensure_route_session(command)
            if self.bridge is None:
                raise RuntimeError("devtools bridge unavailable")
            result = await enable_runtime_js_file(self.bridge, script)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            state.update({"status": "failed", "enabled": False, "message": "启用失败", "error": str(exc)})
            self.emit_js_injection_state(record_id, script_id)
            return
        enabled = bool(result.get("enabled"))
        state.update(
            {
                "status": "enabled" if enabled else "disabled",
                "enabled": enabled,
                "message": str(result.get("message") or ("已启用（当前页面和后续页面）" if enabled else "已取消")),
                "error": "",
                "log": str(result.get("log") or "").strip(),
                "controller_key": str(result.get("controller_key") or state.get("controller_key") or ""),
                "persistent_identifier": str(result.get("persistent_identifier") or state.get("persistent_identifier") or ""),
                "miniapp_epoch": int(self.state.get("miniapp_epoch") or state.get("miniapp_epoch") or 0),
                "auto_restore": bool(command.get("auto_restore", state.get("auto_restore"))),
                "script": dict(script),
            }
        )
        self.emit_js_injection_state(record_id, script_id)

    async def disable_runtime_js_script(self, command: dict) -> None:
        """在当前小程序 runtime 中取消长期 JS 脚本注入。"""
        script = command.get("script") if isinstance(command.get("script"), dict) else {}
        script_id = str(script.get("id") or command.get("script_id") or "").strip()
        record_id = int(command.get("record_id") or 0)
        if not is_runtime_toggle_script(script):
            state = self.ensure_js_injection_state(
                command,
                status="failed",
                message="该脚本不是长期脚本",
                error="script is not runtime toggle",
            )
            state.update({"enabled": False})
            self.emit_js_injection_state(record_id, script_id)
            return
        state = self.ensure_js_injection_state(command, status="disabling", message="正在取消注入", error="")
        self.emit_js_injection_state(record_id, script_id)
        try:
            await self.ensure_route_session(command)
            if self.bridge is None:
                raise RuntimeError("devtools bridge unavailable")
            result = await disable_runtime_js_file(
                self.bridge,
                script,
                persistent_identifier=str(state.get("persistent_identifier") or ""),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            state.update({"status": "failed", "message": "取消注入失败", "error": str(exc)})
            self.emit_js_injection_state(record_id, script_id)
            return
        enabled = bool(result.get("enabled"))
        state.update(
            {
                "status": "enabled" if enabled else "disabled",
                "enabled": enabled,
                "message": str(result.get("message") or ("已启用（当前页面和后续页面）" if enabled else "已取消")),
                "error": "",
                "log": str(result.get("log") or "").strip(),
                "controller_key": str(result.get("controller_key") or state.get("controller_key") or ""),
                "persistent_identifier": str(state.get("persistent_identifier") or "") if enabled else "",
                "miniapp_epoch": int(self.state.get("miniapp_epoch") or state.get("miniapp_epoch") or 0),
                "auto_restore": bool(command.get("auto_restore", state.get("auto_restore"))),
                "script": dict(script),
            }
        )
        self.emit_js_injection_state(record_id, script_id)

    def mark_runtime_toggle_scripts_stale(
        self,
        *,
        owner_key: str,
        record_id: int,
        miniapp_epoch: int,
        message: str,
    ) -> None:
        """在 runtime 失效后，把当前会话下已启用的长期脚本统一标记为 disabled。"""
        normalized_owner_key = str(owner_key or "").strip()
        target_record_id = int(record_id or 0)
        target_epoch = int(miniapp_epoch or 0)
        for current_record_id, states in list(self.js_injection_states.items()):
            if not isinstance(states, dict):
                continue
            for script_id, state in list(states.items()):
                if not isinstance(state, dict) or not is_runtime_toggle_script(state):
                    continue
                state_owner_key = str(state.get("owner_key") or "").strip()
                state_record_id = int(state.get("record_id") or current_record_id or 0)
                if normalized_owner_key:
                    if state_owner_key != normalized_owner_key:
                        continue
                elif target_record_id > 0 and state_record_id != target_record_id:
                    continue
                if not bool(state.get("enabled")) and str(state.get("status") or "") not in {"enabled", "enabling", "disabling"}:
                    continue
                state.update(
                    {
                        "status": "disabled",
                        "enabled": False,
                        "message": str(message or "当前runtime已失效"),
                        "error": "",
                        "persistent_identifier": "",
                        "miniapp_epoch": target_epoch or int(state.get("miniapp_epoch") or 0),
                    }
                )
                self.emit_js_injection_state(state_record_id, str(script_id or state.get("script_id") or ""))

    def schedule_runtime_toggle_auto_restore(self, *, owner_key: str, record_id: int) -> None:
        """在新 runtime 就绪后调度具备资格的长期脚本恢复任务。"""
        if self.bridge is None or not bool(self.state.get("miniapp")):
            return
        session_command = {
            "record_id": int(record_id or 0),
            "owner_key": str(owner_key or "").strip(),
            "display_name": str(self.state.get("display_name") or "").strip(),
            "debug_port": normalize_devtools_port(self.state.get("debug_port"), DEFAULT_MINIAPP_DEBUG_PORT),
            "cdp_port_start": normalize_devtools_port(self.state.get("cdp_port"), DEFAULT_DEVTOOLS_CDP_PORT),
            "automatic": True,
            "auto_restore": True,
        }
        for candidate in build_auto_restore_candidates(
            self.js_injection_states,
            owner_key=str(owner_key or "").strip(),
            record_id=int(record_id or 0),
        ):
            script = dict(candidate.get("script") or {})
            script_id = str(candidate.get("script_id") or script.get("id") or "").strip()
            if not script_id:
                continue
            asyncio.create_task(
                self.schedule_js_injection_task(
                    int(record_id or 0),
                    script_id,
                    self.enable_runtime_js_script({**session_command, "script": script}),
                )
            )

    async def execute_waiting_tap_jump(self, jump_navigator, appid: str, path: str, state: dict, record_id: int) -> dict:
        """准备需要用户弹窗确认的跳转流程，并在等待期间及时回写状态。"""
        for attempt in range(3):
            try:
                prepared = await jump_navigator.prepare_navigate_to_mini_program(appid, path)
                if str(prepared.get("status") or "") != "waiting_tap":
                    return prepared
                state.update(
                    {
                        "status": "executing",
                        "target_path": path,
                        "message": str(prepared.get("message") or "请在小程序内确认跳转"),
                        "error": str(prepared.get("error") or ""),
                    }
                )
                self.emit_jump_state(record_id)
                return await jump_navigator.wait_for_navigation_result(appid, path)
            except Exception as exc:
                if attempt >= 2 or not self.is_transient_miniapp_disconnect_error(exc):
                    raise
                self.mark_waiting_for_miniapp_reconnect()
                state.update(
                    {
                        "status": "executing",
                        "target_path": path,
                        "message": "小程序页面已断开，正在等待回连后重新弹出确认框",
                        "error": "",
                    }
                )
                self.emit_jump_state(record_id)
                await self.wait_for_miniapp_connection()
        raise RuntimeError("miniapp jump reconnect retry exhausted")

    async def cleanup_pending_jump_navigation(self, jump_navigator, appid: str, path: str) -> None:
        """兼容不同 navigator 签名，尽力清理待确认的跳转任务。"""
        if not hasattr(jump_navigator, "cancel_pending_navigation"):
            return
        cancel_method = jump_navigator.cancel_pending_navigation
        try:
            await cancel_method(appid, path)
        except TypeError:
            try:
                await cancel_method(appid)
            except TypeError:
                await cancel_method()

    async def schedule_route_task(self, record_id: int, route_coro) -> None:
        """为指定记录替换掉仍在执行中的路由任务。"""
        await self.cancel_route_task(record_id)
        self.route_tasks[record_id] = asyncio.create_task(self.run_route_task(record_id, route_coro))
        await asyncio.sleep(0)

    async def run_route_task(self, record_id: int, route_coro) -> None:
        """运行单个路由任务，并确保取消不会把 UI 留在 busy 状态。"""
        try:
            await route_coro
        except asyncio.CancelledError:
            self.mark_route_task_cancelled(record_id)
            raise

    def mark_route_task_cancelled(self, record_id: int) -> None:
        """把被取消的路由任务落盘为失败状态，避免按钮永久停在执行中。"""
        state = self.route_states.get(int(record_id or 0))
        if not isinstance(state, dict):
            return
        if str(state.get("status") or "") not in {"starting", "refreshing", "executing", "traversing"}:
            return
        state.update(
            {
                "status": "failed",
                "attached": False,
                "traversing_route": "",
                "message": "路由任务已取消，请重新接管路由",
                "error": "route task cancelled",
            }
        )
        self.emit_route_state(record_id)

    async def cancel_route_task(self, record_id: int) -> None:
        """取消指定记录当前正在执行的路由任务。"""
        task = self.route_tasks.pop(int(record_id or 0), None)
        if task is None:
            return
        if not task.done():
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task

    async def cancel_all_route_tasks(self) -> None:
        """在 worker 退出前取消全部未完成的路由任务。"""
        for record_id in list(self.route_tasks):
            await self.cancel_route_task(record_id)

    async def wait_for_route_task(self, record_id: int) -> None:
        """等待指定记录的路由任务完成，供测试复用。"""
        task = self.route_tasks.get(int(record_id or 0))
        if task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def start_transition(self, command: dict) -> None:
        """停止旧会话，并为目标记录启动新的共享调试会话。"""
        session = self.build_session(command)

        if self.bridge is not None:
            self.state.update({"status": "stopping", "message": "正在停止旧调试会话", "error": ""})
            self.emit_state()
            await self.stop_managed_jump_tasks("小程序跳转已停止，请重新发起")
            await self.cancel_all_js_injection_tasks()
            await self.stop_cloud_poll()
            await self.stop_cloud_runtime()
            self.cloud_state = default_cloud_state(worker_alive=True, message="云函数捕获已停止")
            self.emit_cloud_state()
            await self.stop_bridge()

        self.apply_session_state(
            session,
            status="starting",
            message="正在启动调试",
            error="",
            link="",
            debug_port=self.debug_port_from_command(command),
            cdp_port=0,
            frida=False,
            miniapp=False,
            devtools=False,
        )
        self.emit_state()

        debug_port = self.debug_port_from_command(command)
        cdp_port = 0
        try:
            # 端口探测可能遍历多个端口，放入线程避免拖慢 DevTools worker 事件循环。
            cdp_port = await asyncio.to_thread(self.cdp_port_finder, self.cdp_port_start_from_command(command))
            while True:
                bridge = self.bridge_factory()
                self.bridge = bridge
                try:
                    await bridge.start(session, debug_port, cdp_port, self.handle_bridge_status)
                    break
                except Exception as exc:
                    await self.release_startup_bridge(bridge)
                    if not is_address_in_use_error(exc):
                        raise
                    retry_start = int(cdp_port) + 1
                    if retry_start > CDP_PORT_END:
                        raise
                    retry_port = await asyncio.to_thread(self.cdp_port_finder, retry_start)
                    self.apply_session_state(
                        session,
                        status="starting",
                        message=f"CDP 端口 {cdp_port} 已占用，正在尝试 {retry_port}",
                        error="",
                        link="",
                        debug_port=debug_port,
                        cdp_port=0,
                        frida=False,
                        miniapp=False,
                        devtools=False,
                    )
                    self.emit_state()
                    cdp_port = retry_port
        except asyncio.CancelledError:
            with contextlib.suppress(Exception):
                await self.stop_bridge()
            self.state = default_state(worker_alive=True, message="调试已停止")
            self.emit_state()
            raise
        except Exception as exc:
            with contextlib.suppress(Exception):
                await self.stop_bridge()
            self.apply_session_state(
                session,
                status="failed",
                message=f"启动失败：{exc}",
                error=str(exc),
                link="",
                debug_port=debug_port,
                cdp_port=0,
                frida=False,
                miniapp=False,
                devtools=False,
            )
            self.emit_state()
            return

        self.state.update(
            {
                "status": "running",
                "cdp_port": cdp_port,
                "link": build_devtools_link(cdp_port),
                "error": "",
                "message": self.running_message(),
            }
        )
        self.emit_state()

    async def release_startup_bridge(self, bridge: EngineBridge) -> None:
        """释放启动失败的 bridge，避免残留端口占用影响后续重试。"""
        if self.bridge is bridge:
            self.bridge = None
        self.route_navigator = None
        with contextlib.suppress(Exception):
            await bridge.stop()
        for key in ("frida", "miniapp", "devtools"):
            self.state[key] = False
        self.state["cdp_port"] = 0
        self.state["link"] = ""

    async def stop_transition(self) -> None:
        """停止当前共享调试会话，但保持 worker 继续运行。"""
        await self.cancel_all_route_tasks()
        self.state.update({"status": "stopping", "message": "正在停止调试", "error": ""})
        self.emit_state()
        try:
            await self.stop_managed_jump_tasks("小程序跳转已停止，请重新发起")
            await self.cancel_all_js_injection_tasks()
            await self.stop_cloud_poll()
            await self.stop_cloud_runtime()
            self.cloud_state = default_cloud_state(worker_alive=True, message="云函数捕获已停止")
            self.emit_cloud_state()
            await self.stop_bridge()
        except Exception as exc:
            self.state = default_state(worker_alive=True)
            self.state.update(
                {
                    "status": "failed",
                    "message": f"停止失败：{exc}",
                    "error": str(exc),
                }
            )
            self.emit_state()
            return

        self.state = default_state(worker_alive=True, message="调试已停止")
        self.emit_state()
        self.mark_route_states_stopped("调试已停止，请重新接管路由")

    async def attach_route(self, command: dict) -> None:
        """把路由能力挂到共享会话上，并读取当前可用路由。"""
        record_id = int(command.get("record_id") or 0)
        state = self.ensure_route_state(command, status="starting", message="正在接管路由", error="")
        self.emit_route_state(record_id)
        try:
            await self.ensure_route_session(command)
            payload = await self.run_with_miniapp_reconnect_retry(self.route_navigator.fetch_routes)
        except Exception as exc:
            state.update(
                {
                    "status": "failed",
                    "attached": False,
                    "message": str(exc) or "路由接管失败",
                    "error": str(exc),
                }
            )
            self.emit_route_state(record_id)
            return
        state.update(
            {
                "status": "ready",
                "worker_alive": True,
                "attached": True,
                "pages": payload["pages"],
                "tabbar_pages": payload["tabbar_pages"],
                "current_route": payload["current_route"],
                "traversing_route": "",
                "guard_enabled": bool(payload.get("guard_enabled")),
                "blocked_redirects_count": int(payload.get("blocked_redirects_count") or 0),
                "message": "路由已就绪",
                "error": "",
            }
        )
        self.emit_route_state(record_id)

    async def refresh_routes(self, command: dict) -> None:
        """刷新当前记录对应的小程序路由列表。"""
        record_id = int(command.get("record_id") or 0)
        state = self.ensure_route_state(command, status="refreshing", message="正在刷新路由", error="")
        self.emit_route_state(record_id)
        try:
            await self.ensure_route_session(command)
            payload = await self.run_with_miniapp_reconnect_retry(self.route_navigator.fetch_routes)
        except Exception as exc:
            state.update({"status": "failed", "message": str(exc) or "路由刷新失败", "error": str(exc)})
            self.emit_route_state(record_id)
            return
        state.update(
            {
                "status": "ready",
                "attached": True,
                "pages": payload["pages"],
                "tabbar_pages": payload["tabbar_pages"],
                "current_route": payload["current_route"],
                "traversing_route": "",
                "guard_enabled": bool(payload.get("guard_enabled")),
                "blocked_redirects_count": int(payload.get("blocked_redirects_count") or 0),
                "message": "路由已刷新",
                "error": "",
            }
        )
        self.emit_route_state(record_id)

    async def execute_route_action(self, command: dict) -> None:
        """通过共享调试会话执行指定的路由跳转动作。"""
        record_id = int(command.get("record_id") or 0)
        action = str(command.get("action") or "")
        route = str(command.get("route") or "")
        action_label = ROUTE_ACTION_LABELS.get(action, action)
        state = self.ensure_route_state(command, status="executing", message=f"正在执行{action_label}", error="")
        self.emit_route_state(record_id)
        try:
            await self.ensure_route_session(command)
            explicit_is_tabbar = command.get("is_tabbar")
            if explicit_is_tabbar is None:
                explicit_is_tabbar = is_tabbar_route(route, state.get("pages") if isinstance(state.get("pages"), list) else [])
            resolution = resolve_route_action(
                action,
                route,
                is_tabbar=bool(explicit_is_tabbar),
            )
            handler = getattr(self.route_navigator, resolution.actual_action)
            result = await self.run_with_miniapp_reconnect_retry(lambda: handler(route))
            fallback_used = False
            if should_fallback_to_relaunch(resolution, result):
                fallback_resolution = resolve_route_action("relaunch", route, is_tabbar=bool(explicit_is_tabbar))
                fallback_handler = getattr(self.route_navigator, fallback_resolution.actual_action)
                fallback_result = await self.run_with_miniapp_reconnect_retry(lambda: fallback_handler(route))
                if fallback_result.get("ok"):
                    resolution = fallback_resolution
                    result = fallback_result
                    fallback_used = True
            payload = await self.run_with_miniapp_reconnect_retry(self.route_navigator.fetch_routes) if result.get("ok") else None
        except Exception as exc:
            state.update({"status": "failed", "message": f"{action_label}失败", "error": str(exc)})
            self.emit_route_state(record_id)
            return
        if payload is not None:
            state["pages"] = payload["pages"]
            state["tabbar_pages"] = payload["tabbar_pages"]
            state["guard_enabled"] = bool(payload.get("guard_enabled"))
            state["blocked_redirects_count"] = int(payload.get("blocked_redirects_count") or 0)
        state["current_route"] = str(
            result.get("currentRoute") or (payload or {}).get("current_route") or state.get("current_route") or ""
        )
        state.update(
            {
                "status": "ready" if result.get("ok") else "failed",
                "attached": True,
                "traversing_route": "",
                "last_action": resolution.actual_action,
                "message": build_relaunch_fallback_message()
                if fallback_used and result.get("ok")
                else build_route_action_message(resolution, ok=bool(result.get("ok"))),
                "error": str(result.get("error") or ""),
            }
        )
        self.emit_route_state(record_id)

    async def navigate_back_route(self, command: dict) -> None:
        """通过共享调试会话执行返回上一页动作。"""
        record_id = int(command.get("record_id") or 0)
        state = self.ensure_route_state(command, status="executing", message="正在启动调试", error="")
        self.emit_route_state(record_id)
        try:
            await self.ensure_route_session(command)
            result = await self.run_with_miniapp_reconnect_retry(
                lambda: self.route_navigator.navigate_back(int(command.get("delta") or 1))
            )
            payload = await self.run_with_miniapp_reconnect_retry(self.route_navigator.fetch_routes) if result.get("ok") else None
        except Exception as exc:
            state.update({"status": "failed", "message": ROUTE_ACTION_LABELS["navigate_back"] + "失败", "error": str(exc)})
            self.emit_route_state(record_id)
            return
        if payload is not None:
            state["pages"] = payload["pages"]
            state["tabbar_pages"] = payload["tabbar_pages"]
            state["guard_enabled"] = bool(payload.get("guard_enabled"))
            state["blocked_redirects_count"] = int(payload.get("blocked_redirects_count") or 0)
        state["current_route"] = str(
            result.get("currentRoute") or (payload or {}).get("current_route") or state.get("current_route") or ""
        )
        state.update(
            {
                "status": "ready" if result.get("ok") else "failed",
                "attached": True,
                "traversing_route": "",
                "last_action": "navigate_back",
                "message": "返回完成" if result.get("ok") else "返回失败",
                "error": str(result.get("error") or ""),
            }
        )
        self.emit_route_state(record_id)

    async def traverse_routes(self, command: dict) -> None:
        """依次遍历当前记录的全部路由，并回写最终路由状态。"""
        record_id = int(command.get("record_id") or 0)
        state = self.ensure_route_state(command, status="traversing", message="正在遍历路由", error="")
        self.emit_route_state(record_id)
        raw_delay = command.get("traverse_interval_seconds")
        traverse_delay = normalize_route_traverse_interval(
            self.traverse_route_delay if raw_delay is None else raw_delay
        )
        failures: list[dict] = []
        success_count = 0
        try:
            await self.ensure_route_session(command)
            payload = await self.run_with_miniapp_reconnect_retry(self.route_navigator.fetch_routes)
        except Exception as exc:
            state.update({"status": "failed", "message": str(exc) or "路由遍历失败", "error": str(exc)})
            self.emit_route_state(record_id)
            return

        pages = payload.get("pages") if isinstance(payload.get("pages"), list) else []
        state.update(
            {
                "attached": True,
                "pages": pages,
                "tabbar_pages": payload.get("tabbar_pages", []) if isinstance(payload, dict) else [],
                "current_route": payload.get("current_route", state.get("current_route", ""))
                if isinstance(payload, dict)
                else state.get("current_route", ""),
                "traversing_route": "",
                "guard_enabled": bool(payload.get("guard_enabled")) if isinstance(payload, dict) else bool(state.get("guard_enabled")),
                "blocked_redirects_count": int(payload.get("blocked_redirects_count") or 0)
                if isinstance(payload, dict)
                else int(state.get("blocked_redirects_count") or 0),
            }
        )
        traverse_pages = self.route_pages_from_start(pages, str(command.get("start_route") or ""))
        recovery_page = self.route_recovery_page(pages)
        for index, page in enumerate(traverse_pages):
            route = str(page.get("route") or "").strip()
            if not route:
                continue
            state.update(
                {
                    "status": "traversing",
                    "traversing_route": route,
                    "message": f"正在遍历路由：{route}",
                    "error": self.format_traverse_failures(failures),
                }
            )
            self.emit_route_state(record_id)
            try:
                await self.ensure_route_session(command)
                result = await self.run_with_miniapp_reconnect_retry(
                    lambda route=route, page=page: self.route_navigator.visit_route(
                        route,
                        is_tabbar=bool(page.get("is_tabbar")),
                    )
                )
                if not result.get("ok"):
                    raise RuntimeError(str(result.get("error") or f"遍历路由失败：{route}"))
                success_count += 1
                state["current_route"] = str(result.get("currentRoute") or state.get("current_route") or "")
            except Exception as exc:
                failures.append({"route": route, "error": str(exc)})
                state.update(
                    {
                        "message": f"路由遍历失败，继续后续路由：{route}",
                        "traversing_route": route,
                        "error": self.format_traverse_failures(failures),
                    }
                )
                self.emit_route_state(record_id)
                await self.recover_route_context(command, recovery_page, failures)
            if index < len(traverse_pages) - 1 and traverse_delay > 0:
                await self.sleep_func(traverse_delay)

        try:
            await self.ensure_route_session(command)
            payload = await self.run_with_miniapp_reconnect_retry(self.route_navigator.fetch_routes)
        except Exception as exc:
            failures.append({"route": "刷新路由状态", "error": str(exc)})

        final_status = "ready" if success_count > 0 or not traverse_pages else "failed"
        state.update(
            {
                "status": final_status,
                "attached": final_status == "ready",
                "pages": payload.get("pages", pages) if isinstance(payload, dict) else pages,
                "tabbar_pages": payload.get("tabbar_pages", []) if isinstance(payload, dict) else [],
                "current_route": payload.get("current_route", state.get("current_route", ""))
                if isinstance(payload, dict)
                else state.get("current_route", ""),
                "traversing_route": "",
                "guard_enabled": bool(payload.get("guard_enabled")) if isinstance(payload, dict) else bool(state.get("guard_enabled")),
                "blocked_redirects_count": int(payload.get("blocked_redirects_count") or 0)
                if isinstance(payload, dict)
                else int(state.get("blocked_redirects_count") or 0),
                "message": self.traverse_complete_message(len(traverse_pages), success_count, len(failures)),
                "error": self.format_traverse_failures(failures),
            }
        )
        self.emit_route_state(record_id)

    @staticmethod
    def route_pages_from_start(pages: list[dict], start_route: str) -> list[dict]:
        """根据指定起始路由截取需要遍历的页面列表。"""
        route = str(start_route or "").strip().lstrip("/")
        valid_pages = [dict(page) for page in pages if isinstance(page, dict)]
        if not route:
            return valid_pages
        for index, page in enumerate(valid_pages):
            if str(page.get("route") or "").strip().lstrip("/") == route:
                return valid_pages[index:]
        return valid_pages

    @staticmethod
    def route_recovery_page(pages: list[dict]) -> dict:
        """选择遍历失败后用于恢复上下文的基准路由。"""
        for page in pages:
            if not isinstance(page, dict):
                continue
            route = str(page.get("route") or "").strip()
            if route:
                return dict(page)
        return {}

    async def recover_route_context(self, command: dict, recovery_page: dict, failures: list[dict]) -> None:
        """路由失败后回到基准页面，避免坏页面影响后续跳转。"""
        route = str((recovery_page or {}).get("route") or "").strip()
        if not route:
            return
        try:
            await self.ensure_route_session(command)
            result = await self.run_with_miniapp_reconnect_retry(
                lambda: self.route_navigator.visit_route(route, is_tabbar=bool(recovery_page.get("is_tabbar")))
            )
        except Exception as exc:
            failures.append({"route": f"恢复基准路由 {route}", "error": str(exc)})
            return
        if not result.get("ok"):
            failures.append(
                {
                    "route": f"恢复基准路由 {route}",
                    "error": str(result.get("error") or "恢复失败"),
                }
            )

    @staticmethod
    def format_traverse_failures(failures: list[dict]) -> str:
        """把遍历失败项整理成可展示的简短错误文本。"""
        if not failures:
            return ""
        return "；".join(
            f"{item.get('route') or '未知路由'}：{item.get('error') or '未知错误'}"
            for item in failures[:10]
            if isinstance(item, dict)
        )

    @staticmethod
    def traverse_complete_message(total_count: int, success_count: int, failure_count: int) -> str:
        """生成遍历完成后的状态消息。"""
        if total_count <= 0:
            return "没有可遍历的路由"
        if failure_count > 0:
            return f"遍历完成，成功 {success_count}/{total_count}，跳过 {failure_count} 个失败路由"
        return "遍历完成"

    async def build_debug_runtime(self, command: dict) -> DebugToggleRuntime:
        """确保共享会话和导航桥就绪后构造调试开关运行时。"""
        await self.ensure_route_session(command)
        return self.debug_runtime_factory(self.bridge, self.route_navigator)

    async def detect_debug_toggle(self, command: dict) -> None:
        """检测当前记录对应小程序的调试开关状态。"""
        record_id = int(command.get("record_id") or 0)
        self.emit_debug_log(
            command,
            level="DEBUG",
            stage="command_received",
            action="detect",
            message="正在检测调试状态",
        )
        state = self.ensure_debug_state(
            command,
            status="detecting",
            message="正在检测调试状态",
            error="",
            last_action="detect",
        )
        self.emit_debug_state(record_id)
        try:
            self.emit_debug_log(
                command,
                level="DEBUG",
                stage="prepare_runtime",
                action="detect",
                message=self.describe_debug_runtime_prepare_message(command),
            )
            runtime = await self.build_debug_runtime(command)
            self.emit_debug_log(
                command,
                level="DEBUG",
                stage="runtime_ready",
                action="detect",
                message="调试运行时已就绪",
            )
            result = await runtime.detect()
        except asyncio.CancelledError:
            self.emit_debug_log(
                command,
                level="WARNING",
                stage="cancelled",
                action="detect",
                message="调试状态检测已取消",
            )
            raise
        except Exception as exc:
            self.emit_debug_log(
                command,
                level="ERROR",
                stage="detect_failed",
                action="detect",
                message=f"调试状态检测失败：{exc}",
            )
            state.update({"status": "failed", "message": str(exc) or "调试状态检测失败", "error": str(exc)})
            self.emit_debug_state(record_id)
            return
        self.emit_debug_log(
            command,
            level="INFO",
            stage="detect_result",
            action="detect",
            message=f"调试状态检测完成，debug={bool(result.get('debug_enabled'))}，vConsole={bool(result.get('vconsole_visible'))}",
        )
        state.update(
            {
                "status": "ready",
                "debug_enabled": bool(result.get("debug_enabled")),
                "vconsole_visible": bool(result.get("vconsole_visible")),
                "message": "调试状态检测完成",
                "error": "",
            }
        )
        self.emit_debug_state(record_id)

    async def set_debug_toggle(self, command: dict) -> None:
        """开启或关闭当前记录对应小程序的调试开关，并提示用户重启后再确认结果。"""
        record_id = int(command.get("record_id") or 0)
        enabled = bool(command.get("enabled"))
        action = "enable" if enabled else "disable"
        state = self.ensure_debug_state(
            command,
            status="enabling" if enabled else "disabling",
            message="正在开启调试" if enabled else "正在关闭调试",
            error="",
            last_action=action,
        )
        self.emit_debug_log(
            command,
            level="DEBUG",
            stage="command_received",
            action=action,
            message="正在开启调试" if enabled else "worker 已收到关闭调试命令",
        )
        self.emit_debug_state(record_id)
        try:
            self.emit_debug_log(
                command,
                level="DEBUG",
                stage="prepare_runtime",
                action=action,
                message=self.describe_debug_runtime_prepare_message(command),
            )
            runtime = await self.build_debug_runtime(command)
            self.emit_debug_log(
                command,
                level="DEBUG",
                stage="runtime_ready",
                action=action,
                message=f"调试运行时已就绪，开始调用 wx.setEnableDebug({'true' if enabled else 'false'})",
            )
            await runtime.set_enabled(enabled)
        except asyncio.CancelledError:
            self.emit_debug_log(
                command,
                level="WARNING",
                stage="cancelled",
                action=action,
                message=f"{self.debug_toggle_action_label(action)}任务已取消",
            )
            raise
        except Exception as exc:
            self.emit_debug_log(
                command,
                level="ERROR",
                stage="set_enable_debug_failed",
                action=action,
                message=f"wx.setEnableDebug({'true' if enabled else 'false'}) 调用失败：{exc}",
            )
            state.update({"status": "failed", "message": str(exc) or "调试开关设置失败", "error": str(exc)})
            self.emit_debug_state(record_id)
            return
        self.emit_debug_log(
            command,
            level="INFO",
            stage="set_enable_debug",
            action=action,
            message=f"wx.setEnableDebug({'true' if enabled else 'false'}) 调用成功，请重启小程序等待回连",
        )
        state.update(
            {
                "status": "ready",
                "debug_enabled": enabled,
                "vconsole_visible": False,
                "message": "调试已开启，请重启小程序确认最终效果" if enabled else "调试已关闭，请重启小程序确认最终效果",
                "error": "",
            }
        )
        self.emit_debug_state(record_id)

    async def start_cloud_audit(self, command: dict) -> None:
        """为当前记录启动动态云函数 Hook，并开启轮询任务。"""
        record_id = int(command.get("record_id") or 0)
        self.ensure_cloud_state(command, status="starting", message="正在启动云函数捕获", error="")
        self.emit_cloud_state()
        try:
            await self.ensure_route_session(command)
            state = self.ensure_cloud_state(command, status="starting", message="正在启动云函数捕获", error="")
            if self.cloud_runtime is None:
                self.cloud_runtime = CloudAuditRuntime(self.bridge)
            result = await self.cloud_runtime.start()
        except Exception as exc:
            self.cloud_state.update({"status": "failed", "enabled": False, "message": str(exc) or "云函数捕获启动失败", "error": str(exc)})
            self.emit_cloud_state()
            return
        if not bool(result.get("ok")):
            self.cloud_state.update({"status": "failed", "enabled": False, "message": str(result.get("reason") or "云函数捕获启动失败"), "error": str(result.get("reason") or "")})
            self.emit_cloud_state()
            return
        self.cloud_state.update({"status": "running", "enabled": True, "message": "云函数捕获中", "error": ""})
        self.emit_cloud_state()
        await self.start_cloud_poll(record_id)

    async def stop_cloud_audit(self) -> None:
        """停止动态云函数捕获并清理轮询任务。"""
        self.cloud_state.update({"status": "stopping", "message": "正在停止云函数捕获", "error": ""})
        self.emit_cloud_state()
        await self.stop_cloud_poll()
        await self.stop_cloud_runtime()
        self.cloud_state = default_cloud_state(worker_alive=True, message="云函数捕获已停止")
        self.emit_cloud_state()

    async def clear_cloud_audit(self) -> None:
        """清空当前动态云函数捕获记录。"""
        self.cloud_calls.clear()
        self.cloud_state["captured_count"] = 0
        self.emit_cloud_state()
        if self.cloud_runtime is not None:
            with contextlib.suppress(Exception):
                await self.cloud_runtime.clear()

    async def scan_cloud_static(self, command: dict) -> None:
        """执行一次运行时静态扫描，并把结果发回 UI。"""
        record_id = int(command.get("record_id") or 0)
        try:
            await self.ensure_route_session(command)
            if self.cloud_runtime is None:
                self.cloud_runtime = CloudAuditRuntime(self.bridge)

            def on_progress(message: str) -> None:
                """把运行时静态扫描进度转发给 UI。"""
                self.emit(
                    {
                        "type": "cloud_audit_static_scan_progress",
                        "record_id": record_id,
                        "message": str(message or ""),
                    }
                )

            results = await self.cloud_runtime.static_scan(on_progress=on_progress)
            self.emit(
                {
                    "type": "cloud_audit_static_scan_result",
                    "record_id": record_id,
                    "results": [dict(item) for item in results if isinstance(item, dict)],
                }
            )
        except asyncio.CancelledError:
            return
        except Exception as exc:
            self.emit(
                {
                    "type": "scan_cloud_static_error",
                    "record_id": record_id,
                    "message": str(exc),
                    "traceback": traceback.format_exc(limit=3),
                }
            )

    async def call_cloud_function(self, command: dict) -> None:
        """手动调用目标小程序内的云函数。"""
        record_id = int(command.get("record_id") or 0)
        name = str(command.get("name") or "").strip()
        data = command.get("data") if isinstance(command.get("data"), dict) else {}
        origin = str(command.get("origin") or "manual")
        source_call_id = str(command.get("source_call_id") or "")
        call_id = str(command.get("call_id") or "")
        timeout_seconds = normalize_cloud_call_timeout(
            command.get("timeout_seconds"),
            minimum=0.05,
            maximum=120,
        )
        hard_timeout = cloud_call_transport_timeout(float(timeout_seconds)) + 0.1
        was_enabled = bool(self.cloud_state.get("enabled"))
        self.ensure_cloud_state(command, status="calling", message=f"正在调用 {name}", error="")
        self.emit_cloud_state()
        try:
            raw_result = await asyncio.wait_for(
                self.execute_cloud_function_call(command, name, data, timeout_seconds),
                timeout=hard_timeout,
            )
        except asyncio.TimeoutError:
            raw_result = {
                "ok": False,
                "status": "timeout",
                "name": name,
                "data": data,
                "origin": origin,
                "source_call_id": source_call_id,
                "call_id": call_id,
                "timeout_seconds": timeout_seconds,
                "error": f"调用超时({timeout_seconds}s)",
            }
        except Exception as exc:
            raw_result = {
                "ok": False,
                "status": "fail",
                "name": name,
                "data": data,
                "origin": origin,
                "source_call_id": source_call_id,
                "call_id": call_id,
                "error": str(exc),
            }
        if not isinstance(raw_result, dict):
            raw_result = {
                "ok": False,
                "status": "fail",
                "name": name,
                "data": data,
                "origin": origin,
                "source_call_id": source_call_id,
                "call_id": call_id,
                "error": "返回结果格式错误",
            }
        result = normalize_cloud_call_record(raw_result, default_origin=origin)
        result["name"] = str(result.get("name") or name)
        result["record_id"] = record_id
        result["origin"] = origin
        result["source_call_id"] = source_call_id or str(result.get("source_call_id") or "")
        result["call_id"] = str(result.get("call_id") or call_id or f"{origin}:{name}")
        result["timeout_seconds"] = float(raw_result.get("timeout_seconds") or timeout_seconds)
        result["message"] = str(raw_result.get("message") or "")
        result["ok"] = bool(raw_result.get("ok", result.get("status") == "success"))
        self.cloud_call_history.append(dict(result))
        self.cloud_call_history = self.cloud_call_history[-200:]
        self.emit({"type": "cloud_audit_call_result", "result": dict(result)})
        self.cloud_state.update(
            {
                "status": "running" if was_enabled else "stopped",
                "enabled": was_enabled,
                "message": "云函数捕获中" if was_enabled else "云函数调用完成",
                "error": "",
            }
        )
        self.emit_cloud_state()

    async def execute_cloud_function_call(self, command: dict, name: str, data: dict, timeout_seconds: float) -> dict:
        """执行云函数调用的完整流程，便于在外层统一加硬超时。"""
        await self.ensure_route_session(command)
        self.ensure_cloud_state(command, status="calling", message=f"正在调用 {name}", error="")
        if self.cloud_runtime is None:
            self.cloud_runtime = CloudAuditRuntime(self.bridge)
        return await self.cloud_runtime.call_function(
            name,
            data,
            timeout_seconds=timeout_seconds,
            origin=str(command.get("origin") or "manual"),
            source_call_id=str(command.get("source_call_id") or ""),
            call_id=str(command.get("call_id") or ""),
        )

    async def start_cloud_poll(self, record_id: int) -> None:
        """启动动态云函数轮询任务。"""
        await self.stop_cloud_poll()
        self.cloud_poll_task = asyncio.create_task(self.poll_cloud_calls(record_id))

    async def poll_cloud_calls(self, record_id: int) -> None:
        """轮询新抓到的动态云函数调用并发送到 UI。"""
        try:
            while self.running and self.cloud_state.get("enabled"):
                await self.sleep_func(1.5)
                if self.cloud_runtime is None:
                    continue
                try:
                    calls = await self.cloud_runtime.poll()
                except Exception as exc:
                    if not self.is_transient_miniapp_disconnect_error(exc):
                        raise
                    self.cloud_state.update(
                        {
                            "status": "recovering",
                            "recovering": True,
                            "message": "等待页面上下文恢复",
                            "error": "",
                        }
                    )
                    self.emit_cloud_state()
                    self.mark_waiting_for_miniapp_reconnect()
                    await self.wait_for_miniapp_connection()
                    continue
                runtime_state = self.cloud_runtime.status_snapshot() if hasattr(self.cloud_runtime, "status_snapshot") else {}
                runtime_status = str(runtime_state.get("status") or "")
                if runtime_status == "recovering":
                    self.cloud_state.update(
                        {
                            "status": "recovering",
                            "recovering": True,
                            "message": str(runtime_state.get("message") or "等待页面上下文恢复"),
                            "error": "",
                        }
                    )
                    self.emit_cloud_state()
                    continue
                self.cloud_state.update({"status": "running", "recovering": False, "message": "云函数捕获中", "error": ""})
                if not calls:
                    self.emit_cloud_state()
                    continue
                self.cloud_calls.extend(dict(call) for call in calls if isinstance(call, dict))
                self.cloud_state["captured_count"] = len(self.cloud_calls)
                self.emit({"type": "cloud_audit_calls", "record_id": record_id, "calls": [dict(call) for call in calls if isinstance(call, dict)]})
                self.emit_cloud_state()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.cloud_state.update({"status": "failed", "enabled": False, "message": "云函数捕获异常", "error": str(exc)})
            self.emit_cloud_state()

    async def stop_cloud_poll(self) -> None:
        """取消动态云函数轮询任务。"""
        task = self.cloud_poll_task
        self.cloud_poll_task = None
        if task is None:
            return
        if not task.done():
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task

    async def stop_cloud_runtime(self) -> None:
        """释放动态云函数运行时并恢复原始方法。"""
        runtime = self.cloud_runtime
        self.cloud_runtime = None
        if runtime is not None:
            with contextlib.suppress(Exception):
                await runtime.stop()

    async def schedule_cloud_operation(self, cloud_coro) -> None:
        """替换当前仍在运行的云审计操作任务。"""
        await self.cancel_cloud_operation()
        self.cloud_operation_task = asyncio.create_task(cloud_coro)
        await asyncio.sleep(0)

    async def cancel_cloud_operation(self) -> None:
        """取消当前未完成的云审计操作任务。"""
        task = self.cloud_operation_task
        self.cloud_operation_task = None
        if task is None:
            return
        if not task.done():
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task

    def emit_cloud_state(self) -> None:
        """向 UI 进程发送当前云审计状态快照。"""
        self.event_queue.put({"type": "cloud_audit_state", "state": copy_cloud_state(self.cloud_state)})

    def ensure_cloud_state(self, command: dict, *, status: str, message: str, error: str) -> dict:
        """确保当前记录始终有一份可更新的云审计状态。"""
        session = self.build_session(command)
        record_id = int(session["record_id"] or 0)
        self.cloud_state.update(
            {
                "record_id": record_id,
                "owner_key": session["owner_key"],
                "display_name": session["display_name"],
                "worker_alive": True,
                "status": status,
                "enabled": status == "running",
                "message": message,
                "error": error,
            }
        )
        return self.cloud_state

    def ensure_debug_state(
        self,
        command: dict,
        *,
        status: str,
        message: str,
        error: str,
        last_action: str,
    ) -> dict:
        """确保指定记录始终有一份可更新的调试开关状态缓存。"""
        session = self.build_session(command)
        record_id = int(session["record_id"] or 0)
        state = self.debug_states.setdefault(
            record_id,
            default_debug_toggle_state(
                record_id=record_id,
                owner_key=session["owner_key"],
                display_name=session["display_name"],
                worker_alive=True,
            ),
        )
        state.update(
            {
                "record_id": record_id,
                "owner_key": session["owner_key"],
                "display_name": session["display_name"],
                "worker_alive": True,
                "status": status,
                "message": message,
                "error": error,
                "last_action": last_action,
            }
        )
        return state

    async def toggle_route_guard(self, command: dict) -> None:
        """切换当前记录的防跳转开关，并同步最新守卫状态。"""
        record_id = int(command.get("record_id") or 0)
        enabled = bool(command.get("enabled"))
        state = self.ensure_route_state(
            command,
            status="executing",
            message="正在开启防跳转" if enabled else "正在关闭防跳转",
            error="",
        )
        self.emit_route_state(record_id)
        try:
            await self.ensure_route_session(command)
            if enabled:
                result = await self.run_with_miniapp_reconnect_retry(self.route_navigator.enable_redirect_guard)
            else:
                result = await self.run_with_miniapp_reconnect_retry(self.route_navigator.disable_redirect_guard)
            payload = await self.run_with_miniapp_reconnect_retry(self.route_navigator.fetch_routes)
        except Exception as exc:
            state.update({"status": "failed", "message": str(exc) or "防跳转切换失败", "error": str(exc)})
            self.emit_route_state(record_id)
            return
        state.update(
            {
                "status": "ready" if result.get("ok", True) else "failed",
                "attached": True,
                "pages": payload["pages"],
                "tabbar_pages": payload["tabbar_pages"],
                "current_route": payload["current_route"],
                "traversing_route": "",
                "guard_enabled": bool(payload.get("guard_enabled")),
                "blocked_redirects_count": int(payload.get("blocked_redirects_count") or 0),
                "message": "防跳转已开启" if enabled else "防跳转已关闭",
                "error": str(result.get("error") or ""),
            }
        )
        self.emit_route_state(record_id)

    async def jump_to_mini_program(self, command: dict) -> None:
        """执行单条小程序跳转任务，并按当前会话状态进行隔离。"""
        current_task = asyncio.current_task()
        session = self.build_session(command)
        record_id = int(session["record_id"] or 0)
        appid = str(command.get("appid") or "").strip()
        path = self.normalize_jump_path(command.get("path") or "")
        state = self.ensure_jump_state(
            command,
            status="executing",
            message="正在跳转小程序",
            error="",
            target_appid=appid,
            target_path=path,
            last_action="navigate_to_mini_program",
        )
        self.emit_jump_state(record_id)
        if not appid:
            state.update(
                {
                    "status": "failed",
                    "target_path": path,
                    "message": "小程序 appid 不能为空",
                    "error": "appid is empty",
                }
            )
            self.emit_jump_state(record_id)
            return
        try:
            await self.ensure_route_session(command)
            if self.bridge is None:
                raise RuntimeError("devtools bridge unavailable")
            jump_navigator = self.jump_navigator_factory(self.bridge)
            if hasattr(jump_navigator, "prepare_navigate_to_mini_program") and hasattr(
                jump_navigator, "wait_for_navigation_result"
            ):
                result = await self.execute_waiting_tap_jump(jump_navigator, appid, path, state, record_id)
            else:
                result = await jump_navigator.navigate_to_mini_program(appid, path)
        except asyncio.CancelledError:
            with contextlib.suppress(Exception):
                if "jump_navigator" in locals():
                    await self.cleanup_pending_jump_navigation(jump_navigator, appid, path)
            raise
        except Exception as exc:
            with contextlib.suppress(Exception):
                if "jump_navigator" in locals():
                    await self.cleanup_pending_jump_navigation(jump_navigator, appid, path)
            if self.is_jump_task_invalidated(current_task):
                return
            state.update(
                {
                    "status": "failed",
                    "target_path": path,
                    "message": "小程序跳转失败",
                    "error": str(exc),
                }
            )
            self.emit_jump_state(record_id)
            return
        ok = bool(result.get("ok", True))
        if self.is_jump_task_invalidated(current_task):
            return
        result_status = str(result.get("status") or "")
        state.update(
            {
                "status": "cancelled" if result_status == "cancelled" else ("success" if ok else "failed"),
                "target_appid": appid,
                "target_path": path,
                "last_action": str(result.get("action") or "navigate_to_mini_program"),
                "message": "小程序跳转完成" if ok else self.jump_result_message(result),
                "error": str(result.get("error") or ""),
            }
        )
        self.emit_jump_state(record_id)

    @staticmethod
    def jump_result_message(result: dict) -> str:
        """把跳转结果转换为稳定的中文提示文案。"""
        if not isinstance(result, dict):
            return "小程序跳转失败"
        status = str(result.get("status") or "")
        error_text = str(result.get("error") or "")
        message = str(result.get("message") or "").strip()
        if status == "cancelled":
            return message or "小程序跳转任务已取消"
        if status == "waiting_tap_timeout":
            return "等待在小程序内确认跳转超时"
        if "can only be invoked by user TAP gesture" in error_text:
            return "当前触发不满足微信用户手势限制，请重新发起跳转并在确认框中点击立即跳转"
        if message:
            return message
        return "小程序跳转失败"

    async def ensure_route_session(self, command: dict) -> None:
        """确保共享 bridge 已切到目标记录，且小程序端已重新连上。"""
        session = self.build_session(command)
        needs_switch = (
            self.bridge is None
            or str(self.state.get("owner_key") or "") != session["owner_key"]
            or self.state.get("status") not in {"starting", "running"}
        )
        if needs_switch:
            await self.cancel_transition()
            self.transition_task = asyncio.create_task(self.start_transition(command))
            await self.wait_for_transition()
        elif self.transition_task is not None:
            await self.wait_for_transition()
        if self.bridge is None:
            raise RuntimeError("devtools session unavailable")
        await self.wait_for_miniapp_connection()
        if self.route_navigator is None:
            self.route_navigator = self.navigator_factory(self.bridge)

    async def wait_for_miniapp_connection(self) -> None:
        """在执行路由脚本前等待小程序客户端连接完成。"""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.miniapp_ready_timeout
        while not bool(self.state.get("miniapp")):
            if self.state.get("status") == "failed":
                raise RuntimeError(str(self.state.get("error") or self.state.get("message") or "debug session failed"))
            if self.bridge is None:
                raise RuntimeError("devtools bridge unavailable")
            if loop.time() >= deadline:
                timeout_message = f"等待小程序回连超时，{MINIAPP_RESTART_HINT}"
                self.state["message"] = timeout_message
                self.emit_state()
                raise TimeoutError(timeout_message)
            await self.sleep_func(self.poll_interval)

    @staticmethod
    def is_transient_miniapp_disconnect_error(error: BaseException | str) -> bool:
        """判断异常是否属于页面切换期间可等待回连后重试的瞬时断链。"""
        message = str(error or "")
        lowered = message.lower()
        return any(marker in message or marker in lowered for marker in TRANSIENT_MINIAPP_DISCONNECT_MARKERS)

    def mark_waiting_for_miniapp_reconnect(self) -> None:
        """把共享会话标记为等待小程序重新连接，避免旧在线态导致立即重试。"""
        self.state["miniapp"] = False
        if self.state.get("status") in {"starting", "running"}:
            self.state["message"] = self.running_message()
            self.emit_state()

    async def run_with_miniapp_reconnect_retry(self, operation) -> dict:
        """执行一次依赖小程序上下文的操作，遇到瞬时断链时等待回连后补重试一次。"""
        for attempt in range(2):
            try:
                return await operation()
            except Exception as exc:
                if attempt >= 1 or not self.is_transient_miniapp_disconnect_error(exc):
                    raise
                self.mark_waiting_for_miniapp_reconnect()
                await self.wait_for_miniapp_connection()
        raise RuntimeError("miniapp reconnect retry exhausted")

    def build_session(self, command: dict) -> dict:
        """把记录相关命令整理成统一的会话描述结构。"""
        session = {
            "record_id": int(command.get("record_id") or 0),
            "owner_key": str(command.get("owner_key") or "").strip(),
            "display_name": str(command.get("display_name") or "").strip(),
        }
        if not session["owner_key"]:
            fallback_id = int(session["record_id"] or 0)
            session["owner_key"] = str(fallback_id) if fallback_id > 0 else session["display_name"]
        if not session["display_name"]:
            session["display_name"] = session["owner_key"] or "当前小程序"
        return session

    def debug_toggle_action_label(self, action: str) -> str:
        """返回调试开关动作的中文名称。"""
        return DEBUG_TOGGLE_ACTION_LABELS.get(str(action or "").strip(), "调试开关")

    def describe_debug_runtime_prepare_message(self, command: dict) -> str:
        """根据当前共享会话状态生成更详细的调试准备日志。"""
        session = self.build_session(command)
        owner_key = str(session["owner_key"] or "")
        current_owner_key = str(self.state.get("owner_key") or "")
        status = str(self.state.get("status") or "")
        if self.bridge is None or status not in {"starting", "running"}:
            return "当前无可用调试会话，准备自动启动 DevTools 并等待小程序回连"
        if current_owner_key and current_owner_key != owner_key:
            return "检测到共享调试会话归属不同，准备切换到当前小程序并等待回连"
        if not bool(self.state.get("miniapp")):
            return "共享调试会话已就绪，正在等待小程序重新连接"
        return "复用当前共享调试会话，准备直接执行调试脚本"

    def ensure_route_state(self, command: dict, *, status: str, message: str, error: str) -> dict:
        """确保指定记录始终持有一份可更新的路由状态缓存。"""
        session = self.build_session(command)
        record_id = int(session["record_id"] or 0)
        state = self.route_states.setdefault(
            record_id,
            default_route_state(
                record_id=record_id,
                owner_key=session["owner_key"],
                display_name=session["display_name"],
                worker_alive=True,
            ),
        )
        state.update(
            {
                "record_id": record_id,
                "owner_key": session["owner_key"],
                "display_name": session["display_name"],
                "worker_alive": True,
                "status": status,
                "traversing_route": state.get("traversing_route", "") if status == "traversing" else "",
                "message": message,
                "error": error,
            }
        )
        return state

    @staticmethod
    def debug_port_from_command(command: dict) -> int:
        """从命令中读取并归一化小程序回连端口。"""
        return normalize_devtools_port(command.get("debug_port"), DEFAULT_MINIAPP_DEBUG_PORT)

    @staticmethod
    def cdp_port_start_from_command(command: dict) -> int:
        """从命令中读取并归一化 DevTools 代理起始端口。"""
        return normalize_devtools_port(command.get("cdp_port_start"), DEFAULT_DEVTOOLS_CDP_PORT)

    def mark_route_states_stopped(self, message: str) -> None:
        """调试会话停止后同步清理所有已接管的路由状态。"""
        for record_id, state in list(self.route_states.items()):
            if not isinstance(state, dict):
                continue
            state.update(
                {
                    "status": "stopped",
                    "attached": False,
                    "worker_alive": True,
                    "traversing_route": "",
                    "message": str(message or "调试已停止，请重新接管路由"),
                    "error": "",
                }
            )
            self.emit_route_state(record_id)

    def mark_jump_states_stopped(self, message: str) -> None:
        """调试会话停止后同步清理所有已接管的跳转状态。"""
        for record_id, state in list(self.jump_states.items()):
            if not isinstance(state, dict):
                continue
            state.update(
                {
                    "status": "stopped",
                    "worker_alive": True,
                    "message": str(message or "小程序跳转已停止，请重新发起"),
                    "error": "",
                }
            )
            self.emit_jump_state(record_id)

    def apply_session_state(
        self,
        session: dict,
        *,
        status: str,
        message: str,
        error: str,
        link: str,
        debug_port: int,
        cdp_port: int,
        frida: bool,
        miniapp: bool,
        devtools: bool,
        miniapp_epoch: int | None = None,
    ) -> None:
        """按指定会话拥有者更新全局调试状态快照。"""
        self.state.update(
            {
                "status": status,
                "worker_alive": True,
                "owner_key": str(session.get("owner_key") or ""),
                "display_name": str(session.get("display_name") or ""),
                "record_id": int(session.get("record_id") or 0),
                "debug_port": normalize_devtools_port(debug_port, DEFAULT_MINIAPP_DEBUG_PORT),
                "cdp_port": int(cdp_port or 0),
                "link": link,
                "frida": bool(frida),
                "miniapp": bool(miniapp),
                "miniapp_epoch": int(miniapp_epoch or self.state.get("miniapp_epoch") or 0),
                "devtools": bool(devtools),
                "message": message,
                "error": error,
            }
        )

    def handle_bridge_status(self, status: dict) -> None:
        """把 bridge 连通性变化合并进全局调试状态。"""
        previous_miniapp_connected = bool(self.state.get("miniapp"))
        next_miniapp_connected = bool(status.get("miniapp", False))
        owner_key = str(self.state.get("owner_key") or "")
        record_id = int(self.state.get("record_id") or 0)
        previous_epoch = int(self.state.get("miniapp_epoch") or 0)
        next_epoch = int(status.get("miniapp_epoch") or previous_epoch)
        if previous_miniapp_connected and not next_miniapp_connected:
            if owner_key:
                self.injected_js_signatures.pop(owner_key, None)
            self.mark_runtime_toggle_scripts_stale(
                owner_key=owner_key,
                record_id=record_id,
                miniapp_epoch=next_epoch or previous_epoch,
                message="当前runtime已失效",
            )
        if next_miniapp_connected and next_epoch != previous_epoch:
            if owner_key:
                self.injected_js_signatures.pop(owner_key, None)
            self.mark_runtime_toggle_scripts_stale(
                owner_key=owner_key,
                record_id=record_id,
                miniapp_epoch=next_epoch,
                message="当前runtime已失效",
            )
        for key in ("frida", "miniapp", "devtools"):
            self.state[key] = bool(status.get(key, False))
        self.state["miniapp_epoch"] = next_epoch
        if next_miniapp_connected and next_epoch != previous_epoch:
            self.schedule_runtime_toggle_auto_restore(owner_key=owner_key, record_id=record_id)
        if self.state.get("status") in {"starting", "running"}:
            self.state["message"] = self.running_message()
            self.emit_state()

    def running_message(self) -> str:
        """生成用于界面展示的简洁会话状态文案。"""
        parts = [
            "Frida 已连接" if self.state.get("frida") else "Frida 未连接",
            "小程序已回连" if self.state.get("miniapp") else "等待小程序回连",
            "DevTools 已连接" if self.state.get("devtools") else "等待 DevTools 连接",
        ]
        return " | ".join(parts)

    async def stop_bridge(self) -> None:
        """停止当前 bridge，并清理会话中的瞬时连接状态。"""
        bridge = self.bridge
        owner_key = str(self.state.get("owner_key") or "")
        record_id = int(self.state.get("record_id") or 0)
        miniapp_epoch = int(self.state.get("miniapp_epoch") or 0)
        self.bridge = None
        self.route_navigator = None
        self.injected_js_signatures.clear()
        self.mark_runtime_toggle_scripts_stale(
            owner_key=owner_key,
            record_id=record_id,
            miniapp_epoch=miniapp_epoch,
            message="当前runtime已失效",
        )
        await self.stop_cloud_poll()
        await self.stop_cloud_runtime()
        self.cloud_state = default_cloud_state(worker_alive=True, message="云函数捕获已停止")
        self.emit_cloud_state()
        if bridge is not None:
            await bridge.stop()
        for key in ("frida", "miniapp", "devtools"):
            self.state[key] = False
        self.state["cdp_port"] = 0
        self.state["link"] = ""


def devtools_worker_main(event_queue: mp.Queue, command_queue: mp.Queue) -> None:
    """共享 DevTools worker 进程入口。"""
    asyncio.run(AsyncDevtoolsWorker(event_queue, command_queue).run())


