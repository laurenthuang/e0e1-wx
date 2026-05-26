"""为跨小程序跳转页从正则缓存提取目标 AppID。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from package.decompiler.auto_cache import load_auto_match_summary
from package.miniapp_jump.identifiers import extract_wechat_appids_from_match_results, extract_wechat_appids_from_match_summary


class JumpIdentifierTaskMixin:
    """提供跨小程序跳转候选 AppID 提取任务。"""

    async def run_extract_jump_identifiers(self, task_id: int, payload: dict) -> None:
        """从自动处理缓存读取正则结果并提取去重后的 AppID。"""
        cache_path = Path(str(payload.get("cache_path") or "")).expanduser()
        applet_id = str(payload.get("applet_id") or "").strip()
        legacy_applet_id = str(payload.get("legacy_applet_id") or "").strip()
        new_folders = payload.get("new_folders") if isinstance(payload.get("new_folders"), list) else []
        raw_dirs = payload.get("output_dirs") if isinstance(payload.get("output_dirs"), list) else []
        output_dirs = [Path(str(path or "")).expanduser() for path in raw_dirs]
        fallback_results = payload.get("fallback_results") if isinstance(payload.get("fallback_results"), list) else []

        def load_and_extract() -> list[str]:
            """在线程中执行缓存读取和结果提取，避免阻塞 worker 事件循环。"""
            summary = load_auto_match_summary(cache_path, applet_id, legacy_applet_id, new_folders, output_dirs)
            appids = extract_wechat_appids_from_match_summary(summary)
            if appids:
                return appids
            return extract_wechat_appids_from_match_results(fallback_results)

        appids = await asyncio.to_thread(load_and_extract)
        self.emit({"type": "jump_identifiers_loaded", "task_id": task_id, "appids": appids, "count": len(appids)})
