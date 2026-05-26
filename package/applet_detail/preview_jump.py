"""管理反编译详情页搜索和匹配结果的自动预览定位辅助函数。"""

from __future__ import annotations


def match_result_identity(result: dict) -> tuple:
    """返回匹配结果的去重标识。"""
    return (
        str(result.get("file_path") or ""),
        int(result.get("line_number") or 0),
        int(result.get("match_start") or 0),
        int(result.get("match_end") or 0),
        str(result.get("match_text") or ""),
    )


def first_valid_match_result(results: list[dict]) -> dict:
    """返回第一条包含文件路径的匹配结果。"""
    for result in results:
        if isinstance(result, dict) and str(result.get("file_path") or "").strip():
            return dict(result)
    return {}


def preferred_match_result(selected_result: dict, results: list[dict]) -> dict:
    """优先返回已选结果，否则返回第一条可定位结果。"""
    if isinstance(selected_result, dict) and str(selected_result.get("file_path") or "").strip():
        return dict(selected_result)
    return first_valid_match_result(results)
