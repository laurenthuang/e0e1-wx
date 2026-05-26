"""JS 文件注入功能包入口，按需导出扫描服务、模型和 UI 组件。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from package.js_injection.service import JsInjectionCatalogService
    from package.js_injection.widgets import JsInjectionDialog, JsInjectionPage

__all__ = [
    "JsInjectionCatalogService",
    "JsInjectionDialog",
    "JsInjectionPage",
    "scan_js_catalog",
    "script_id_for_path",
]


def __getattr__(name: str):
    """按需导入 JS 注入子模块，避免主窗口启动时扫描相关依赖提前加载。"""
    if name == "JsInjectionCatalogService":
        from package.js_injection.service import JsInjectionCatalogService

        return JsInjectionCatalogService
    if name == "JsInjectionDialog":
        from package.js_injection.widgets import JsInjectionDialog

        return JsInjectionDialog
    if name == "JsInjectionPage":
        from package.js_injection.widgets import JsInjectionPage

        return JsInjectionPage
    if name in {"scan_js_catalog", "script_id_for_path"}:
        from package.js_injection import catalog

        return getattr(catalog, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
