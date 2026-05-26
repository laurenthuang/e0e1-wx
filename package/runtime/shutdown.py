"""提供 Qt/qasync 程序的 Ctrl+C 安全退出桥接。"""

from __future__ import annotations

import signal
from types import FrameType
from typing import Callable

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication


class CtrlCShutdownBridge:
    """把终端 Ctrl+C 转换为 QApplication.quit() 调度。"""

    def __init__(
        self,
        app: QApplication,
        *,
        signal_module=signal,
        timer_factory: Callable[[QApplication], QTimer] = QTimer,
        quit_scheduler: Callable[[QApplication], None] | None = None,
        interval_ms: int = 100,
    ) -> None:
        """保存应用、信号模块和轻量唤醒定时器依赖。"""
        self.app = app
        self.signal_module = signal_module
        self.timer_factory = timer_factory
        self.quit_scheduler = quit_scheduler or (lambda current_app: QTimer.singleShot(0, current_app.quit))
        self.interval_ms = int(interval_ms or 100)
        self.previous_handler = None
        self.timer = None
        self.installed = False

    def install(self) -> "CtrlCShutdownBridge":
        """安装 SIGINT 处理器并启动轻量定时器。"""
        if self.installed:
            return self
        self.previous_handler = self.signal_module.getsignal(self.signal_module.SIGINT)
        self.signal_module.signal(self.signal_module.SIGINT, self._handle_sigint)
        self.timer = self.timer_factory(self.app)
        self.timer.setInterval(self.interval_ms)
        self.timer.timeout.connect(self._keep_python_signal_handling_responsive)
        self.timer.start()
        self.installed = True
        return self

    def uninstall(self) -> None:
        """卸载 SIGINT 处理器并恢复旧处理器。"""
        if self.timer is not None:
            self.timer.stop()
        if self.installed:
            self.signal_module.signal(self.signal_module.SIGINT, self.previous_handler)
        self.installed = False

    def _handle_sigint(self, _signum: int, _frame: FrameType | None) -> None:
        """收到 Ctrl+C 后调度 Qt 应用退出。"""
        self.quit_scheduler(self.app)

    def _keep_python_signal_handling_responsive(self) -> None:
        """空回调用于让 Qt 事件循环周期性回到 Python 层处理信号。"""
        return None


def install_ctrl_c_shutdown(app: QApplication) -> CtrlCShutdownBridge:
    """为 QApplication 安装 Ctrl+C 退出桥接器。"""
    return CtrlCShutdownBridge(app).install()
