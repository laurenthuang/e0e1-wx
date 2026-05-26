"""封装 QApplication 与 qasync 事件循环的启动流程。"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable

from PySide6.QtWidgets import QApplication, QMainWindow
from qasync import QEventLoop

from package.runtime.high_dpi import configure_high_dpi_for_qt
from package.runtime.shutdown import install_ctrl_c_shutdown
from package.ui.styles import APP_STYLESHEET


WindowFactory = Callable[[], QMainWindow]


def configure_application(app: QApplication) -> None:
    """配置应用元数据与全局样式。"""
    app.setApplicationName("e0e1-wx-gui")
    app.setOrganizationName("e0e1")
    app.setStyleSheet(APP_STYLESHEET)


def create_qasync_loop(app: QApplication) -> QEventLoop:
    """基于 QApplication 创建 qasync 事件循环。"""
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)
    return loop


async def wait_for_application_exit(window_factory: WindowFactory) -> int:
    """显示主窗口并等待 QApplication 退出。"""
    app = QApplication.instance()
    if app is None:
        raise RuntimeError("QApplication must exist before waiting for exit")

    window = window_factory()
    window.show()

    finished = asyncio.Event()
    app.aboutToQuit.connect(finished.set)
    await finished.wait()
    return 0


def run_qasync_window(window_factory: WindowFactory) -> int:
    """启动 QApplication，并以 qasync 事件循环托管主窗口。"""
    configure_high_dpi_for_qt()
    app = QApplication.instance() or QApplication(sys.argv)
    configure_application(app)
    loop = create_qasync_loop(app)
    shutdown_bridge = install_ctrl_c_shutdown(app)
    try:
        with loop:
            return loop.run_until_complete(wait_for_application_exit(window_factory))
    finally:
        shutdown_bridge.uninstall()
