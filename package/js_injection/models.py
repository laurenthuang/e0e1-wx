"""定义 JS 注入脚本模式和状态辅助方法。"""

from __future__ import annotations


SCRIPT_MODE_ONCE = "once"
SCRIPT_MODE_RUNTIME_TOGGLE = "runtime_toggle"
VALID_SCRIPT_MODES = {SCRIPT_MODE_ONCE, SCRIPT_MODE_RUNTIME_TOGGLE}


def normalize_script_mode(value) -> str:
    """把脚本模式归一化为受支持的固定字符串。"""
    mode = str(value or "").strip().casefold()
    if mode == SCRIPT_MODE_RUNTIME_TOGGLE:
        return SCRIPT_MODE_RUNTIME_TOGGLE
    return SCRIPT_MODE_ONCE


def is_runtime_toggle_script(script: dict) -> bool:
    """判断脚本是否属于可启用/可取消的长期脚本。"""
    if not isinstance(script, dict):
        return False
    return normalize_script_mode(script.get("mode")) == SCRIPT_MODE_RUNTIME_TOGGLE
