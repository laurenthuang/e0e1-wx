"""小程序监控包入口，延迟导出控制器和分页常量。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from package.monitor.controller import MiniProgramMonitor

__all__ = ["MiniProgramMonitor", "PAGE_SIZE"]


def __getattr__(name: str):
    """按需导入监控实现，避免启动阶段预加载 Windows 扫描 worker。"""
    if name == "MiniProgramMonitor":
        from package.monitor.controller import MiniProgramMonitor

        return MiniProgramMonitor
    if name == "PAGE_SIZE":
        from package.monitor.constants import PAGE_SIZE

        return PAGE_SIZE
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
