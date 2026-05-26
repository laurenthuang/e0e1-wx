"""云审计模块公共入口，按需导出模型、运行时和 worker 调度器。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from package.cloud_audit.runner import CloudAuditTaskRunner
    from package.cloud_audit.runtime import CloudAuditRuntime
    from package.cloud_audit.scanner import CloudSourceScanner

__all__ = [
    "CloudAuditRuntime",
    "CloudAuditTaskRunner",
    "CloudSourceScanner",
    "build_cloud_call_replay_payload",
    "build_report_payload",
    "build_static_template",
    "cloud_audit_cache_path",
    "cloud_call_detail_rows",
    "cloud_call_row_values",
    "copy_cloud_state",
    "default_cloud_state",
    "entry_template",
    "format_json_text",
    "load_cloud_audit_entry",
    "merge_cloud_call_history",
    "normalize_cloud_call_record",
    "normalize_dynamic_call",
    "normalize_static_entry",
    "save_cloud_audit_entry",
]


def __getattr__(name: str):
    """按需导入云审计子模块，避免主窗口启动时加载扫描与反编译依赖。"""
    if name in {
        "build_report_payload",
        "build_static_template",
        "copy_cloud_state",
        "default_cloud_state",
        "entry_template",
        "format_json_text",
        "normalize_dynamic_call",
        "normalize_static_entry",
    }:
        from package.cloud_audit import models

        return getattr(models, name)
    if name in {
        "build_cloud_call_replay_payload",
        "cloud_call_detail_rows",
        "cloud_call_row_values",
        "merge_cloud_call_history",
        "normalize_cloud_call_record",
    }:
        from package.cloud_audit import history

        return getattr(history, name)
    if name == "CloudAuditTaskRunner":
        from package.cloud_audit.runner import CloudAuditTaskRunner

        return CloudAuditTaskRunner
    if name == "CloudAuditRuntime":
        from package.cloud_audit.runtime import CloudAuditRuntime

        return CloudAuditRuntime
    if name == "CloudSourceScanner":
        from package.cloud_audit.scanner import CloudSourceScanner

        return CloudSourceScanner
    if name in {"cloud_audit_cache_path", "load_cloud_audit_entry", "save_cloud_audit_entry"}:
        from package.cloud_audit import cache

        return getattr(cache, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
