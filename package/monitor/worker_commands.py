"""Handle delete, hide, rebind, and stop commands from the UI process."""

from __future__ import annotations

import asyncio
import queue
import time
from pathlib import Path

from package.cleanup import RecordCleanupRequest
from package.decompiler.cache_keys import output_dirs_for_folders


class MonitorCommandMixin:
    async def process_commands(self) -> None:
        """处理 UI 进程发送过来的监控命令。"""
        changed = False
        while True:
            try:
                command = self.command_queue.get_nowait()
            except queue.Empty:
                break
            command_type = command.get("type")
            if command_type == "stop":
                self.running = False
                return
            try:
                if command_type == "delete":
                    await self.delete_record(int(command.get("id", 0)), str(command.get("output_root") or ""))
                    changed = True
                elif command_type == "delete_many":
                    await self.delete_many_records(command.get("ids"), str(command.get("output_root") or ""))
                    changed = True
                elif command_type == "hide":
                    self.hide_record(int(command.get("id", 0)))
                    changed = True
                elif command_type == "rebind":
                    await self.rebind_record(int(command.get("id", 0)))
                    changed = True
            except Exception as exc:
                self.emit({"type": "error", "message": f"处理监控命令失败：{exc}"})
        if changed:
            self.publish_records(force=True)

    async def delete_record(self, record_id: int, output_root: str = "") -> None:
        """删除记录并把磁盘清理提交到后台任务，不阻塞命令循环。"""
        assert self.conn is not None
        row = self.conn.execute(
            "SELECT wxid, wxids, packages_root FROM applet WHERE id = ?",
            (record_id,),
        ).fetchone()
        if row is not None:
            cleanup_request = self.build_delete_cleanup_request(record_id, row, output_root)
            self.conn.execute("DELETE FROM applet WHERE id = ?", (record_id,))
            self.conn.commit()
            if cleanup_request is not None and hasattr(self, "schedule_record_cleanup"):
                self.schedule_record_cleanup(cleanup_request)
            return
        self.conn.execute("DELETE FROM applet WHERE id = ?", (record_id,))
        self.conn.commit()

    async def delete_many_records(self, record_ids, output_root: str = "") -> None:
        """批量删除记录，并让每条记录继续复用独立后台清理流程。"""
        ids = [int(item or 0) for item in record_ids] if isinstance(record_ids, list) else []
        for record_id in ids:
            if record_id > 0:
                await self.delete_record(record_id, output_root)

    def build_delete_cleanup_request(self, record_id: int, row, output_root: str) -> RecordCleanupRequest | None:
        """根据记录行生成后台删除清理请求。"""
        output_root_text = str(output_root or "").strip()
        if not output_root_text:
            return None

        raw_wxids = self.decode_wxids(row["wxids"], str(row["wxid"] or ""))
        wxids = list(raw_wxids)
        packages_root = str(row["packages_root"] or "").strip()
        if packages_root and hasattr(self, "normalize_record_wxids"):
            wxids = self.normalize_record_wxids(wxids, packages_root)

        cache_keys = self.build_delete_cache_keys(record_id, row, wxids, raw_wxids)
        package_dirs: list[Path] = []
        if packages_root:
            package_root_path = Path(packages_root).expanduser()
            for wxid in wxids:
                package_dirs.append(package_root_path / wxid)
        output_root_path = Path(output_root_text).expanduser()
        return RecordCleanupRequest(
            output_root=output_root_path,
            output_dirs=output_dirs_for_folders(output_root_path, wxids),
            packages_root=Path(packages_root).expanduser() if packages_root else Path(),
            package_dirs=package_dirs,
            cache_keys=cache_keys,
            new_folders=wxids,
        )

    def build_delete_cache_keys(self, record_id: int, row, wxids: list[str], raw_wxids: list[str]) -> list[str]:
        """生成删除记录时需要一并清理的缓存键集合。"""
        cache_keys: list[str] = []
        for group in (wxids, raw_wxids):
            normalized_group = [str(item).strip() for item in group if str(item).strip()]
            if normalized_group:
                cache_keys.append("|".join(normalized_group))
                cache_keys.extend(normalized_group)
        primary_wxid = str(row["wxid"] or "").strip()
        if primary_wxid:
            cache_keys.append(primary_wxid)
        cache_keys.append(str(record_id))
        deduped_keys: list[str] = []
        seen: set[str] = set()
        for key in cache_keys:
            if key and key not in seen:
                deduped_keys.append(key)
                seen.add(key)
        return deduped_keys

    def hide_record(self, record_id: int) -> None:
        """隐藏记录但保留数据库数据。"""
        assert self.conn is not None
        self.conn.execute("UPDATE applet SET hidden = 1 WHERE id = ?", (record_id,))
        self.conn.commit()

    async def rebind_record(self, record_id: int) -> None:
        """把记录重新绑定到最新的未占用 wxid 目录。"""
        assert self.conn is not None
        existing_wxid_keys = self.existing_wxid_keys(exclude_record_id=record_id)
        current_dirs = await asyncio.to_thread(self.snapshot_dirs)
        available = [
            (packages_root, wxid, created_at)
            for packages_root, wxid, created_at in self.flatten_snapshot_dirs(current_dirs)
            if self.wxid_identity_key(packages_root, wxid) not in existing_wxid_keys
        ]
        if not available:
            self.emit({"type": "warning", "message": "未找到可用于重新绑定的新 wxid 文件夹。"})
            return

        latest_group = sorted(self.group_new_dir_entries(available), key=lambda item: item[2], reverse=True)[0]
        packages_root, wxids, created_at = latest_group
        normalized_wxids = self.normalize_wxids(wxids)
        primary_wxid = normalized_wxids[0]
        windows = await self.stable_windows(retry=True)
        window = windows[-1] if windows else {"title": "", "pid": 0, "start_time": created_at}
        existing = self.conn.execute(
            "SELECT id, wxid, wxids, name, window_title FROM applet WHERE id = ?",
            (record_id,),
        ).fetchone()
        title = str(window.get("title") or "").strip()
        name = self.choose_record_name(title, existing, normalized_wxids)
        window_title = self.choose_window_title(title, existing, normalized_wxids)
        self.conn.execute(
            """
            UPDATE applet
            SET wxid = ?, wxids = ?, packages_root = ?, name = ?, window_title = ?, pid = ?, start_time = ?, last_seen = ?, status = ?, created_at = ?, hidden = 0
            WHERE id = ?
            """,
            (
                primary_wxid,
                self.encode_wxids(normalized_wxids),
                self.normalize_packages_root(packages_root),
                name,
                window_title,
                int(window.get("pid") or 0),
                float(window.get("start_time") or created_at),
                time.time(),
                1 if int(window.get("pid") or 0) else 0,
                created_at,
                record_id,
            ),
        )
        self.conn.commit()
