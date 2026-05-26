"""执行 wxapkg 自动发现、解包和反编译进度上报。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from package.decompiler.constants import DECOMPILE_MAX_PARALLEL_PACKAGES
from package.decompiler.core import (
    WxapkgCancelledError,
    find_wxapkg_files,
    normalize_new_folder_names,
    path_inside_root,
    safe_output_folder_path,
)
from package.decompiler.process_pool import run_decompile_jobs


class DecompileTaskMixin:
    async def run_decompile(self, task_id: int, payload: dict) -> None:
        """执行一个小程序记录的 wxapkg 自动反编译任务。"""
        packages_root = Path(str(payload.get("packages_root") or "")).expanduser()
        output_root = Path(str(payload.get("output_root") or "output")).expanduser()
        new_folders = normalize_new_folder_names(payload.get("new_folders") if isinstance(payload.get("new_folders"), list) else [])
        summary = await self.execute_decompile(task_id, packages_root, output_root, new_folders)
        self.emit({"type": "decompile_result", "task_id": task_id, "summary": summary})

    async def execute_decompile(
        self,
        task_id: int,
        packages_root: Path,
        output_root: Path,
        new_folders: list[str],
        applet_id: str = "",
    ) -> dict:
        """执行反编译核心流程并返回汇总结果。"""
        output_dirs: list[Path] = []
        context = self.event_context(applet_id)
        summary = {
            "output_dir": str(output_root),
            "output_dirs": [],
            "folder_count": len(new_folders),
            "package_count": 0,
            "extracted_count": 0,
            "errors": [],
        }
        self.emit({"type": "decompile_started", "task_id": task_id, "summary": summary, **context})

        if not new_folders:
            return summary

        cancel_callback = self.task_cancel_event(task_id).is_set if hasattr(self, "task_cancel_event") else None
        folder_records: list[dict] = []
        all_jobs: list[dict] = []
        for new_folder in new_folders:
            await asyncio.sleep(0)
            if hasattr(self, "raise_if_task_cancelled"):
                self.raise_if_task_cancelled(task_id)
            source_dir = packages_root / new_folder
            folder_output_dir = safe_output_folder_path(output_root, new_folder, "new_folder")
            if not path_inside_root(packages_root, source_dir):
                message = f"已跳过非法 new_folder 路径：{new_folder}"
                summary["errors"].append(message)
                self.emit({"type": "decompile_folder_error", "task_id": task_id, "new_folder": new_folder, "message": message, **context})
                continue

            if hasattr(self, "raise_if_task_cancelled"):
                self.raise_if_task_cancelled(task_id)
            if not await asyncio.to_thread(source_dir.is_dir):
                message = f"new_folder 目录不存在：{source_dir}"
                summary["errors"].append(message)
                self.emit({"type": "decompile_folder_error", "task_id": task_id, "new_folder": new_folder, "message": message, **context})
                continue

            if hasattr(self, "raise_if_task_cancelled"):
                self.raise_if_task_cancelled(task_id)
            wxapkg_files = await asyncio.to_thread(find_wxapkg_files, source_dir)
            output_dirs.append(folder_output_dir)
            await asyncio.to_thread(folder_output_dir.mkdir, parents=True, exist_ok=True)
            self.emit(
                {
                    "type": "decompile_folder_started",
                    "task_id": task_id,
                    "new_folder": new_folder,
                    "source_dir": str(source_dir),
                    "output_dir": str(folder_output_dir),
                    "package_count": len(wxapkg_files),
                    **context,
                }
            )
            jobs = [
                {
                    "source_dir": str(source_dir),
                    "output_dir": str(folder_output_dir),
                    "wxapkg_path": str(Path(str(info.get("path") or ""))),
                    "new_folder": new_folder,
                }
                for info in wxapkg_files
            ]
            folder_records.append(
                {
                    "new_folder": new_folder,
                    "source_dir": source_dir,
                    "output_dir": folder_output_dir,
                    "wxapkg_files": wxapkg_files,
                }
            )
            all_jobs.extend(jobs)

        results_by_folder: dict[str, list[dict]] = {}
        if all_jobs:
            results = await run_decompile_jobs(
                jobs=all_jobs,
                max_workers=DECOMPILE_MAX_PARALLEL_PACKAGES,
                is_cancelled=cancel_callback or (lambda: False),
            )
            for result in results:
                folder_name = str(result.get("new_folder") or "")
                results_by_folder.setdefault(folder_name, []).append(result)

        for folder_record in folder_records:
            new_folder = str(folder_record.get("new_folder") or "")
            folder_output_dir = Path(folder_record.get("output_dir") or output_root)
            wxapkg_files = list(folder_record.get("wxapkg_files") or [])
            folder_results = results_by_folder.get(new_folder, [])

            for index, result in enumerate(folder_results, start=1):
                await asyncio.sleep(0)
                if hasattr(self, "raise_if_task_cancelled"):
                    self.raise_if_task_cancelled(task_id)
                wxapkg_path = Path(str(result.get("wxapkg_path") or ""))
                if bool(result.get("ok")):
                    summary["package_count"] += 1
                    summary["extracted_count"] += int(result.get("file_count") or 0)
                    self.emit(
                        {
                            "type": "decompile_progress",
                            "task_id": task_id,
                            "new_folder": new_folder,
                            "index": index,
                            "total": len(wxapkg_files),
                            "wxapkg_path": str(wxapkg_path),
                            "output_dir": str(result.get("output_dir") or folder_output_dir),
                            "file_count": int(result.get("file_count") or 0),
                            **context,
                        }
                    )
                    continue
                error_text = str(result.get("error") or "未知错误")
                if error_text == WxapkgCancelledError.__name__:
                    raise asyncio.CancelledError
                message = f"{wxapkg_path.name} 反编译失败：{error_text}"
                summary["errors"].append(message)
                self.emit(
                    {
                        "type": "decompile_file_error",
                        "task_id": task_id,
                        "new_folder": new_folder,
                        "wxapkg_path": str(wxapkg_path),
                        "message": message,
                        **context,
                    }
                )

            self.emit(
                {
                    "type": "decompile_folder_done",
                    "task_id": task_id,
                    "new_folder": new_folder,
                    "output_dir": str(folder_output_dir),
                    "package_count": len(wxapkg_files),
                    **context,
                }
            )

        summary["output_dirs"] = [str(path) for path in output_dirs]
        return summary
