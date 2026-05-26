"""wxapkg 反编译功能包入口，延迟导出任务调度器。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from package.decompiler.runner import DecompileTaskRunner

__all__ = ["DecompileTaskRunner"]


def __getattr__(name: str):
    """按需导入反编译 runner，避免启动阶段加载解包 worker。"""
    if name == "DecompileTaskRunner":
        from package.decompiler.runner import DecompileTaskRunner

        return DecompileTaskRunner
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
