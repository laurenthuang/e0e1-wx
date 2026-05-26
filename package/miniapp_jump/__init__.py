"""跨小程序跳转模块导出。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from package.miniapp_jump.navigator import MiniAppJumpNavigator
    from package.miniapp_jump.page import MiniAppJumpPage

__all__ = [
    "MiniAppJumpNavigator",
    "MiniAppJumpPage",
    "copy_miniapp_jump_state",
    "default_miniapp_jump_state",
    "load_jump_js",
    "normalize_miniapp_jump_state",
    "read_jump_js",
]


def __getattr__(name: str):
    """按需导入跳转模块对象，避免后台 worker 导入 UI 页面形成循环。"""
    if name in {"MiniAppJumpNavigator", "load_jump_js", "read_jump_js"}:
        from package.miniapp_jump.navigator import MiniAppJumpNavigator, load_jump_js, read_jump_js

        values = {
            "MiniAppJumpNavigator": MiniAppJumpNavigator,
            "load_jump_js": load_jump_js,
            "read_jump_js": read_jump_js,
        }
        return values[name]
    if name == "MiniAppJumpPage":
        from package.miniapp_jump.page import MiniAppJumpPage

        return MiniAppJumpPage
    if name in {"copy_miniapp_jump_state", "default_miniapp_jump_state", "normalize_miniapp_jump_state"}:
        from package.miniapp_jump.state import copy_miniapp_jump_state, default_miniapp_jump_state, normalize_miniapp_jump_state

        values = {
            "copy_miniapp_jump_state": copy_miniapp_jump_state,
            "default_miniapp_jump_state": default_miniapp_jump_state,
            "normalize_miniapp_jump_state": normalize_miniapp_jump_state,
        }
        return values[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
