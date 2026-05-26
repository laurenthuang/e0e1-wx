"""程序启动入口，仅负责多进程准备和 GUI 事件循环调度。"""

from __future__ import annotations
import multiprocessing as mp


def main() -> int:
    """程序主入口，只负责启动 qasync 与主窗口。"""
    mp.freeze_support()
    from package.runtime.process_bootstrap import configure_multiprocessing_for_gui_subprocesses

    configure_multiprocessing_for_gui_subprocesses()
    from package.runtime.async_app import run_qasync_window
    from package.ui.main_window import MainWindow

    return run_qasync_window(MainWindow)


if __name__ == "__main__":
    mp.freeze_support()
    raise SystemExit(main())
