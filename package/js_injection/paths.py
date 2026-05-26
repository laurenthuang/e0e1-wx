"""集中管理 JS 注入功能使用的本地路径。"""

from __future__ import annotations

from pathlib import Path


def project_root_path() -> Path:
    """返回项目根目录路径。"""
    return Path(__file__).resolve().parents[2]


def tools_js_dir_path() -> Path:
    """返回自动扫描的 tools/js 目录。"""
    return project_root_path() / "tools" / "js"
