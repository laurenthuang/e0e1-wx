"""维护监控记录快照并计算卡片差异。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class MonitorRecordDiff:
    """描述两次监控记录快照之间的差异。"""

    added_ids: set[int] = field(default_factory=set)
    updated_ids: set[int] = field(default_factory=set)
    removed_ids: set[int] = field(default_factory=set)


class MonitorRecordStore:
    """按 record_id 缓存最新记录，并输出增量差异。"""

    def __init__(self) -> None:
        """初始化空记录快照。"""
        self.records_by_id: dict[int, dict] = {}

    def apply_records(self, records: list[dict]) -> MonitorRecordDiff:
        """更新记录快照并返回新增、更新、删除集合。"""
        next_records = {int(record.get("id") or 0): dict(record) for record in records if int(record.get("id") or 0) > 0}
        current_ids = set(self.records_by_id)
        next_ids = set(next_records)

        diff = MonitorRecordDiff(
            added_ids=next_ids - current_ids,
            removed_ids=current_ids - next_ids,
        )
        for record_id in current_ids & next_ids:
            if next_records[record_id] != self.records_by_id[record_id]:
                diff.updated_ids.add(record_id)

        self.records_by_id = next_records
        return diff
