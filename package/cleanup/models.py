"""定义记录删除清理请求与结果。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class RecordCleanupRequest:
    """描述一次记录删除所需的所有磁盘清理输入。"""

    output_root: Path
    output_dirs: list[Path] = field(default_factory=list)
    packages_root: Path = field(default_factory=Path)
    package_dirs: list[Path] = field(default_factory=list)
    cache_keys: list[str] = field(default_factory=list)
    new_folders: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RecordCleanupResult:
    """描述一次记录删除后的清理统计。"""

    deleted_output_dirs: int = 0
    deleted_packages_dirs: int = 0
    deleted_cache_entries: int = 0
    warnings: list[str] = field(default_factory=list)
