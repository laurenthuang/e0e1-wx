"""提供小程序卡片批量删除的记录筛选工具。"""

from __future__ import annotations


def closed_record_ids(records: list[dict]) -> list[int]:
    """提取已关闭且 ID 有效的小程序卡片记录 ID。"""
    ids: list[int] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        record_id = int(record.get("id") or 0)
        if record_id <= 0:
            continue
        if int(record.get("status") or 0) == 1:
            continue
        ids.append(record_id)
    return ids
