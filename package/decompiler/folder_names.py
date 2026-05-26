"""提供轻量级 new_folder 名称规范化工具，避免启动时导入反编译核心。"""

from __future__ import annotations


def normalize_new_folder_names(values: list[str] | tuple[str, ...] | None) -> list[str]:
    """规范化记录中的 new_folder 名称列表，并保持原始顺序去重。"""
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        normalized.append(text)
        seen.add(text)
    return normalized
