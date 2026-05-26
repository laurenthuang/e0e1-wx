"""执行删除记录后的实际文件与缓存清理。"""

from __future__ import annotations

import shutil
import threading
from collections.abc import Callable
from pathlib import Path

from package.cleanup.models import RecordCleanupRequest, RecordCleanupResult
from package.cloud_audit.cache import cloud_audit_cache_path, delete_cloud_audit_entries
from package.decompiler.auto_cache import delete_auto_process_entries, delete_legacy_match_entries
from package.decompiler.cache_keys import auto_process_cache_path
from package.decompiler.core import path_inside_root


CacheDeleteFunc = Callable[[Path, list[str]], int]

_CACHE_DELETE_RETRY_ATTEMPTS = 3
_CACHE_DELETE_RETRY_DELAY_SECONDS = 0.05
_CACHE_DELETE_RETRY_EVENT = threading.Event()


class RecordCleanupWorker:
    """在后台线程或子进程中执行记录清理。"""

    def cleanup(self, request: RecordCleanupRequest) -> RecordCleanupResult:
        """按请求删除 output、packages 和共享缓存中的对应内容。"""
        result = RecordCleanupResult()
        output_root = Path(request.output_root).expanduser()

        for output_dir in request.output_dirs:
            folder = Path(output_dir).expanduser()
            self._delete_output_dir(result, output_root, folder)

        if request.cache_keys:
            self._delete_cache_entries(
                result,
                "自动处理缓存",
                auto_process_cache_path(output_root),
                request.cache_keys,
                delete_auto_process_entries,
            )
            self._delete_cache_entries(
                result,
                "云审计缓存",
                cloud_audit_cache_path(output_root),
                request.cache_keys,
                delete_cloud_audit_entries,
            )
            self._delete_legacy_match_entries(result, output_root, request)

        packages_root = Path(request.packages_root).expanduser()
        for package_dir in request.package_dirs:
            folder = Path(package_dir).expanduser()
            self._delete_package_dir(result, packages_root, folder)
        return result

    def _delete_output_dir(self, result: RecordCleanupResult, output_root: Path, folder: Path) -> None:
        """安全删除单个 output 输出目录，失败时只记录告警。"""
        try:
            if folder == output_root or not path_inside_root(output_root, folder) or not folder.is_dir():
                return
            shutil.rmtree(folder)
            self._remove_empty_parent_dirs(output_root, folder.parent)
        except OSError as exc:
            self._append_warning(result, f"删除 output 输出目录失败：{folder}，{exc}")
            return
        result.deleted_output_dirs += 1

    def _delete_cache_entries(
        self,
        result: RecordCleanupResult,
        label: str,
        cache_path: Path,
        cache_keys: list[str],
        delete_func: CacheDeleteFunc,
    ) -> None:
        """安全删除共享缓存条目，文件短暂占用时自动重试后再决定是否跳过。"""
        for attempt in range(1, _CACHE_DELETE_RETRY_ATTEMPTS + 1):
            try:
                deleted_count = delete_func(cache_path, cache_keys)
                result.deleted_cache_entries += max(0, int(deleted_count or 0))
                return
            except OSError as exc:
                if attempt < _CACHE_DELETE_RETRY_ATTEMPTS:
                    _CACHE_DELETE_RETRY_EVENT.wait(_CACHE_DELETE_RETRY_DELAY_SECONDS * attempt)
                    continue
                self._append_warning(result, f"{label}文件被占用或写入失败，已跳过：{cache_path}，{exc}")
                return
            except Exception as exc:
                self._append_warning(result, f"{label}清理失败，已跳过：{cache_path}，{exc}")
                return

    def _delete_package_dir(self, result: RecordCleanupResult, packages_root: Path, folder: Path) -> None:
        """安全删除单个小程序包目录，失败时只记录告警。"""
        try:
            if (
                not packages_root
                or folder == packages_root
                or not folder.is_dir()
                or not path_inside_root(packages_root, folder)
            ):
                return
            shutil.rmtree(folder)
            self._remove_empty_parent_dirs(packages_root, folder.parent)
        except OSError as exc:
            self._append_warning(result, f"删除小程序包目录失败：{folder}，{exc}")
            return
        result.deleted_packages_dirs += 1

    def _delete_legacy_match_entries(self, result: RecordCleanupResult, output_root: Path, request: RecordCleanupRequest) -> None:
        """安全删除旧详情页正则匹配缓存中的关联条目。"""
        try:
            deleted_count = delete_legacy_match_entries(
                auto_process_cache_path(output_root),
                request.cache_keys,
                [Path(path).expanduser() for path in request.output_dirs],
                list(request.new_folders),
            )
            result.deleted_cache_entries += max(0, int(deleted_count or 0))
        except Exception as exc:
            self._append_warning(result, f"旧版匹配缓存清理失败，已跳过：{exc}")

    def _remove_empty_parent_dirs(self, root: Path, start_dir: Path) -> None:
        """从叶子目录向上删除空父目录，但绝不删除清理根目录。"""
        parent = Path(start_dir).expanduser()
        root_path = Path(root).expanduser()
        while parent != root_path and path_inside_root(root_path, parent):
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent

    def _append_warning(self, result: RecordCleanupResult, message: str) -> None:
        """向清理结果追加中文告警，交给调用方转发到 UI。"""
        result.warnings.append(message)
