"""定义 JS 长期脚本覆盖模式及其兼容转换。"""

from __future__ import annotations


SCRIPT_OVERRIDE_FOLLOW_DECLARED = ""
SCRIPT_OVERRIDE_ONCE = "once"
SCRIPT_OVERRIDE_RUNTIME_TOGGLE = "runtime_toggle"
VALID_SCRIPT_OVERRIDE_VALUES = {
    SCRIPT_OVERRIDE_FOLLOW_DECLARED,
    SCRIPT_OVERRIDE_ONCE,
    SCRIPT_OVERRIDE_RUNTIME_TOGGLE,
}


def coerce_runtime_toggle_override_value(value) -> str:
    """把旧布尔值和新字符串值统一归一化为覆盖模式字符串。"""
    if value is True:
        return SCRIPT_OVERRIDE_RUNTIME_TOGGLE
    if value is False:
        return SCRIPT_OVERRIDE_ONCE
    normalized = str(value or "").strip().casefold()
    if normalized in {SCRIPT_OVERRIDE_ONCE, SCRIPT_OVERRIDE_RUNTIME_TOGGLE}:
        return normalized
    return SCRIPT_OVERRIDE_FOLLOW_DECLARED


def resolve_script_mode_override(declared_mode: str, override_mode: str) -> tuple[str, str]:
    """根据文件头默认模式和主页面覆盖模式返回声明模式和最终模式。"""
    normalized_declared = SCRIPT_OVERRIDE_RUNTIME_TOGGLE if str(declared_mode or "").strip().casefold() == SCRIPT_OVERRIDE_RUNTIME_TOGGLE else SCRIPT_OVERRIDE_ONCE
    normalized_override = coerce_runtime_toggle_override_value(override_mode)
    if normalized_override == SCRIPT_OVERRIDE_RUNTIME_TOGGLE:
        return normalized_declared, SCRIPT_OVERRIDE_RUNTIME_TOGGLE
    if normalized_override == SCRIPT_OVERRIDE_ONCE:
        return normalized_declared, SCRIPT_OVERRIDE_ONCE
    return normalized_declared, normalized_declared
