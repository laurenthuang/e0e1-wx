"""集中配置 Qt 高 DPI 启动属性，改善 Windows 高分辨率屏幕字体渲染。"""

from __future__ import annotations

import os
from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication


def _configure_windows_dpi_awareness() -> None:
    """在 Windows 上尽早启用进程级 DPI 感知，失败时保持 Qt 默认行为。"""
    try:
        import ctypes

        shcore = getattr(ctypes, "windll", None).shcore
        shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            import ctypes

            user32 = getattr(ctypes, "windll", None).user32
            user32.SetProcessDPIAware()
        except Exception:
            return


def _safe_set_application_attribute(application_cls, attribute) -> None:
    """安全设置 QApplication 属性，兼容不同 Qt 版本中的属性差异。"""
    if attribute is None:
        return
    try:
        application_cls.setAttribute(attribute, True)
    except (AttributeError, RuntimeError, TypeError):
        return


def _safe_set_rounding_policy(gui_application_cls, policy) -> None:
    """安全设置 High DPI 缩放舍入策略，避免旧版本 Qt 缺失接口导致启动失败。"""
    if policy is None:
        return
    try:
        gui_application_cls.setHighDpiScaleFactorRoundingPolicy(policy)
    except (AttributeError, RuntimeError, TypeError):
        return


def configure_high_dpi_for_qt(
    *,
    application_cls=QApplication,
    gui_application_cls=QGuiApplication,
    qt_namespace=Qt,
    os_name: str | None = None,
    dpi_awareness_configurer: Callable[[], None] | None = None,
) -> None:
    """在 QApplication 创建前配置 Qt 高 DPI 属性和 Windows DPI 感知。"""
    current_os_name = os.name if os_name is None else os_name
    if current_os_name == "nt":
        configurer = dpi_awareness_configurer or _configure_windows_dpi_awareness
        try:
            configurer()
        except Exception:
            pass

    attributes = getattr(qt_namespace, "ApplicationAttribute", None)
    if attributes is not None:
        _safe_set_application_attribute(application_cls, getattr(attributes, "AA_EnableHighDpiScaling", None))
        _safe_set_application_attribute(application_cls, getattr(attributes, "AA_UseHighDpiPixmaps", None))

    rounding_policy = getattr(qt_namespace, "HighDpiScaleFactorRoundingPolicy", None)
    if rounding_policy is not None:
        _safe_set_rounding_policy(gui_application_cls, getattr(rounding_policy, "PassThrough", None))
