"""暴露记录删除清理服务。"""

from __future__ import annotations

from package.cleanup.models import RecordCleanupRequest, RecordCleanupResult
from package.cleanup.worker import RecordCleanupWorker


def cleanup_record_assets(request: RecordCleanupRequest) -> RecordCleanupResult:
    """执行一次记录删除后的全部磁盘清理。"""
    return RecordCleanupWorker().cleanup(request)
