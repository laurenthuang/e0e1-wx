"""运行时异步启动层与任务管理导出。"""

from __future__ import annotations

from typing import Any


__all__ = [
    "TaskEvent",
    "TaskHandle",
    "TaskSupervisor",
    "UiLatencyTracker",
    "CtrlCShutdownBridge",
    "configure_application",
    "configure_multiprocessing_for_gui_subprocesses",
    "create_qasync_loop",
    "install_ctrl_c_shutdown",
    "run_qasync_window",
]


def __getattr__(name: str) -> Any:
    """按需导入运行时对象，避免入口 bootstrap 提前加载 Qt。"""
    if name in {"configure_application", "create_qasync_loop", "run_qasync_window"}:
        from package.runtime import async_app

        return getattr(async_app, name)
    if name in {"TaskEvent", "TaskHandle"}:
        from package.runtime import models

        return getattr(models, name)
    if name in {"CtrlCShutdownBridge", "install_ctrl_c_shutdown"}:
        from package.runtime import shutdown

        return getattr(shutdown, name)
    if name == "TaskSupervisor":
        from package.runtime.task_supervisor import TaskSupervisor

        return TaskSupervisor
    if name == "UiLatencyTracker":
        from package.runtime.ui_metrics import UiLatencyTracker

        return UiLatencyTracker
    if name == "configure_multiprocessing_for_gui_subprocesses":
        from package.runtime.process_bootstrap import configure_multiprocessing_for_gui_subprocesses

        return configure_multiprocessing_for_gui_subprocesses
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
