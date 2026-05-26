"""执行正则匹配扫描和匹配结果文件导出。"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path

from package.content_scanner import RegexContentScanner
from package.decompiler.auto_cache import read_auto_process_cache, save_auto_process_entry
from package.decompiler.cache_keys import normalized_path_text, output_signature, rules_signature


class MatchTaskMixin:
    async def run_scan_matches(self, task_id: int, payload: dict) -> None:
        """执行反编译输出目录正则匹配扫描任务。"""
        raw_dirs = payload.get("output_dirs") if isinstance(payload.get("output_dirs"), list) else []
        output_dirs = [Path(str(path or "")).expanduser() for path in raw_dirs]
        rules = payload.get("rules") if isinstance(payload.get("rules"), list) else []
        applet_id = str(payload.get("applet_id") or "").strip()
        summary = await self.execute_scan_matches(task_id, output_dirs, rules, applet_id)
        cache_path = Path(str(payload.get("cache_path") or "")).expanduser()
        if applet_id and str(cache_path):
            new_folders = payload.get("new_folders") if isinstance(payload.get("new_folders"), list) else []
            await self.save_scan_match_summary(cache_path, applet_id, output_dirs, rules, summary, new_folders)
        self.emit({"type": "match_scan_result", "task_id": task_id, "summary": summary})

    async def execute_scan_matches(self, task_id: int, output_dirs: list[Path], rules: list[dict], applet_id: str = "") -> dict:
        """执行正则匹配扫描核心流程并返回汇总结果。"""
        context = self.event_context(applet_id)
        cancel_event = self.cancel_events.get(task_id)
        if cancel_event is None:
            cancel_event = threading.Event()
            self.cancel_events[task_id] = cancel_event

        def progress_callback(summary: dict) -> None:
            """从扫描线程向 UI 发送进度事件。"""
            self.emit({"type": "match_scan_progress", "task_id": task_id, "summary": summary, **context})

        try:
            scanner = RegexContentScanner(rules, progress_callback=progress_callback, cancel_event=cancel_event)
            self.emit(
                {
                    "type": "match_scan_started",
                    "task_id": task_id,
                    "rule_count": len(scanner.rules),
                    "output_dirs": [str(path) for path in output_dirs],
                    **context,
                }
            )
            return await asyncio.to_thread(scanner.scan, output_dirs)
        finally:
            self.cancel_events.pop(task_id, None)
    async def run_export_matches(self, task_id: int, payload: dict) -> None:
        """导出匹配结果到 JSON 或 TXT 文件。"""
        output_path = Path(str(payload.get("path") or "")).expanduser()
        export_format = str(payload.get("format") or "json").lower()
        results = payload.get("results") if isinstance(payload.get("results"), list) else []
        await asyncio.to_thread(self.export_match_results, output_path, export_format, results)
        self.emit({"type": "export_matches_result", "task_id": task_id, "path": str(output_path), "count": len(results)})

    def export_match_results(self, output_path: Path, export_format: str, results: list[dict]) -> None:
        """在后台线程中写出匹配结果文件。"""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if export_format == "txt":
            lines = []
            for result in results:
                lines.append(
                    f"[{result.get('rule_name') or '-'}] "
                    f"{result.get('file_path') or ''}:{int(result.get('line_number') or 0)} "
                    f"{result.get('match_text') or ''}"
                )
            output_path.write_text("\n".join(lines), encoding="utf-8")
            return
        output_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    async def save_scan_match_summary(
        self,
        cache_path: Path,
        applet_id: str,
        output_dirs: list[Path],
        rules: list[dict],
        summary: dict,
        new_folders: list[str],
    ) -> None:
        """把详情页手动扫描结果写入自动处理缓存，供其他功能页复用。"""
        output_signature_value = await asyncio.to_thread(output_signature, output_dirs)
        rules_signature_value = rules_signature(rules)

        def save_entry() -> None:
            """在 worker 后台线程中合并写入缓存文件。"""
            cache = read_auto_process_cache(cache_path)
            applets = cache.get("applets") if isinstance(cache.get("applets"), dict) else {}
            previous = applets.get(str(applet_id)) if isinstance(applets.get(str(applet_id)), dict) else {}
            entry = dict(previous)
            entry.update(
                {
                    "applet_id": str(applet_id),
                    "status": entry.get("status") or "done",
                    "message": entry.get("message") or "正则匹配结果已保存",
                    "regex_processed": True,
                    "new_folders": [str(item) for item in new_folders],
                    "output_dirs": [normalized_path_text(path) for path in output_dirs],
                    "updated_at": time.time(),
                }
            )
            entry["matches"] = {
                "processed": True,
                "cached": False,
                "summary": summary,
                "output_signature": output_signature_value,
                "rules_signature": rules_signature_value,
                "updated_at": time.time(),
            }
            entry["regex_result"] = summary
            save_auto_process_entry(cache_path, str(applet_id), entry)

        await asyncio.to_thread(save_entry)
