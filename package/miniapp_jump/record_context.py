"""为跨小程序跳转页构建与反编译缓存一致的记录上下文。"""

from __future__ import annotations

from pathlib import Path

from package.decompiler.cache_keys import output_dirs_for_folders
from package.decompiler.constants import AUTO_PROCESS_CACHE_DIR_NAME, AUTO_PROCESS_CACHE_FILE_NAME
from package.decompiler.core import normalize_new_folder_names


def record_new_folders(record: dict) -> list[str]:
    """从小程序记录中解析绑定的 new_folder 列表。"""
    raw_list = record.get("wxids_list")
    if isinstance(raw_list, list):
        return normalize_new_folder_names([str(item) for item in raw_list])
    display = str(record.get("wxids_display") or "").strip()
    if display:
        return normalize_new_folder_names([part.strip() for part in display.split(",")])
    return normalize_new_folder_names([str(record.get("wxid") or "")])


def applet_cache_id(record: dict) -> str:
    """生成与自动处理缓存一致的小程序缓存 ID。"""
    folders = record_new_folders(record)
    if folders:
        return "|".join(folders)
    return str(int(record.get("id") or 0))


def output_root(record: dict) -> Path:
    """返回当前记录使用的 output 根目录。"""
    return Path(str(record.get("_output_root") or "output")).expanduser()


def auto_process_cache_path(record: dict) -> Path:
    """返回当前记录对应的自动处理缓存文件路径。"""
    root = output_root(record)
    state = record.get("_processing_state") if isinstance(record.get("_processing_state"), dict) else {}
    raw_path = str(state.get("cache_path") or "").strip()
    if raw_path:
        return Path(raw_path).expanduser()
    return root / AUTO_PROCESS_CACHE_DIR_NAME / AUTO_PROCESS_CACHE_FILE_NAME


def output_dirs(record: dict) -> list[Path]:
    """返回当前记录对应的反编译输出目录。"""
    state = record.get("_processing_state") if isinstance(record.get("_processing_state"), dict) else {}
    raw_dirs = state.get("output_dirs") if isinstance(state.get("output_dirs"), list) else []
    dirs = [Path(str(path or "")).expanduser() for path in raw_dirs if str(path or "").strip()]
    if dirs:
        return dirs
    return output_dirs_for_folders(output_root(record), record_new_folders(record))


def fallback_match_results(record: dict) -> list[dict]:
    """从压缩处理状态中提取可作为兜底的预览匹配结果。"""
    state = record.get("_processing_state") if isinstance(record.get("_processing_state"), dict) else {}
    match_summary = state.get("regex_result") if isinstance(state.get("regex_result"), dict) else {}
    if isinstance(match_summary.get("results"), list):
        return [dict(item) for item in match_summary.get("results", []) if isinstance(item, dict)]
    if isinstance(match_summary.get("preview_results"), list):
        return [dict(item) for item in match_summary.get("preview_results", []) if isinstance(item, dict)]
    matches = state.get("matches") if isinstance(state.get("matches"), dict) else {}
    summary = matches.get("summary") if isinstance(matches.get("summary"), dict) else {}
    if isinstance(summary.get("preview_results"), list):
        return [dict(item) for item in summary.get("preview_results", []) if isinstance(item, dict)]
    return []


def jump_identifier_payload(record: dict) -> dict:
    """生成后台提取跳转候选 AppID 所需的 payload。"""
    return {
        "cache_path": str(auto_process_cache_path(record)),
        "applet_id": applet_cache_id(record),
        "legacy_applet_id": str(int(record.get("id") or 0)),
        "new_folders": record_new_folders(record),
        "output_dirs": [str(path) for path in output_dirs(record)],
        "fallback_results": fallback_match_results(record),
    }
