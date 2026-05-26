"""调度小程序卡片创建后的后台反编译、优化和正则扫描任务。"""

from __future__ import annotations

import copy
import hashlib
import json
import queue
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QTimer, Signal

from package.decompiler.folder_names import normalize_new_folder_names

if TYPE_CHECKING:
    from package.decompiler.runner import DecompileTaskRunner


AUTO_PROCESS_CACHE_DIR_NAME = ".e0e1_cache"
AUTO_PROCESS_CACHE_FILE_NAME = "applet_processing_state.json"
AUTO_PROCESS_EVENT_BATCH_LIMIT = 80
AUTO_PROCESS_RESTART_DEBOUNCE_MS = 900


def create_decompile_runner() -> "DecompileTaskRunner":
    """按需创建反编译任务 runner，避免主窗口启动时拉起 worker。"""
    from package.decompiler.runner import DecompileTaskRunner

    return DecompileTaskRunner()


def record_new_folders(record: dict) -> list[str]:
    """从小程序记录中解析绑定的 new_folder 列表。"""
    raw_list = record.get("wxids_list")
    if isinstance(raw_list, list):
        return normalize_new_folder_names([str(item) for item in raw_list])
    display = str(record.get("wxids_display") or "").strip()
    if display:
        return normalize_new_folder_names([part.strip() for part in display.split(",")])
    return normalize_new_folder_names([str(record.get("wxid") or "")])


def enabled_rules(record: dict) -> list[dict]:
    """提取当前自动处理需要使用的启用正则规则。"""
    rules = record.get("_regex_rules")
    if not isinstance(rules, list):
        return []
    return [dict(rule) for rule in rules if isinstance(rule, dict) and bool(rule.get("enabled", True))]


def applet_cache_id(record: dict) -> str:
    """生成跨数据库记录稳定的小程序缓存标识。"""
    new_folders = record_new_folders(record)
    if new_folders:
        return "|".join(new_folders)
    return str(int(record.get("id") or 0))


def compact_match_summary(summary: dict) -> dict:
    """移除正则命中明细，避免 UI 线程复制大列表。"""
    if not isinstance(summary, dict):
        return {}
    compact = {key: value for key, value in summary.items() if key != "results"}
    results = summary.get("results")
    if isinstance(results, list):
        compact["match_count"] = int(summary.get("match_count") or len(results))
        compact["preview_results"] = [dict(item) for item in results[:20] if isinstance(item, dict)]
        compact["results_loaded"] = False
    elif isinstance(summary.get("preview_results"), list):
        compact["preview_results"] = [dict(item) for item in summary.get("preview_results", []) if isinstance(item, dict)]
        compact["results_loaded"] = bool(summary.get("results_loaded"))
    return compact


def compact_processing_state(state: dict) -> dict:
    """压缩自动处理状态，只保留界面状态与按需加载所需字段。"""
    if not isinstance(state, dict):
        return {}
    compact = {}
    for key, value in state.items():
        if key == "regex_result":
            compact[key] = compact_match_summary(value if isinstance(value, dict) else {})
        elif key == "matches" and isinstance(value, dict):
            section = dict(value)
            if isinstance(section.get("summary"), dict):
                section["summary"] = compact_match_summary(section["summary"])
            compact[key] = section
        else:
            compact[key] = value
    return compact


class AppletAutoProcessManager(QObject):
    """负责卡片级自动反编译、优化和正则扫描任务的轻量调度。"""

    processing_updated = Signal(int, dict)

    def __init__(self, parent: QObject | None = None) -> None:
        """初始化后台任务 runner、去重表和事件轮询定时器。"""
        super().__init__(parent)
        self.runner: DecompileTaskRunner | None = None
        self.active_tasks: dict[int, int] = {}
        self.task_records: dict[int, int] = {}
        self.task_signatures: dict[int, str] = {}
        self.record_signatures: dict[int, str] = {}
        self.pending_records: dict[int, dict] = {}
        self.pending_signatures: dict[int, str] = {}
        self.snapshots: dict[int, dict] = {}
        self.closed = False

        self.event_timer = QTimer(self)
        self.event_timer.timeout.connect(self.process_events)
        self.event_timer.start(100)
        self.restart_timer = QTimer(self)
        self.restart_timer.setSingleShot(True)
        self.restart_timer.timeout.connect(self.flush_pending_records)

    def cache_path(self, output_root: Path) -> Path:
        """返回自动处理流水线共享缓存文件路径。"""
        return output_root / AUTO_PROCESS_CACHE_DIR_NAME / AUTO_PROCESS_CACHE_FILE_NAME

    def ensure_runner(self) -> "DecompileTaskRunner":
        """按需启动独立反编译 worker。"""
        if self.runner is None:
            self.runner = create_decompile_runner()
        return self.runner

    def should_auto_process(self, record: dict) -> bool:
        """判断当前记录是否需要在卡片创建时自动处理。"""
        return (
            int(record.get("id") or 0) > 0
            and int(record.get("status") or 0) == 1
            and bool(record.get("_decompile_enabled"))
            and bool(record_new_folders(record))
        )

    def request_signature(self, record: dict) -> str:
        """生成轻量请求签名，避免每次刷新卡片都重复提交任务。"""
        rules = [
            {
                "name": str(rule.get("name") or ""),
                "pattern": str(rule.get("pattern") or ""),
                "enabled": bool(rule.get("enabled", True)),
            }
            for rule in enabled_rules(record)
        ]
        payload = {
            "id": int(record.get("id") or 0),
            "applet_cache_id": applet_cache_id(record),
            "new_folders": record_new_folders(record),
            "packages_root": str(record.get("_packages_root") or ""),
            "output_root": str(record.get("_output_root") or "output"),
            "optimize_code": bool(record.get("_optimize_code_enabled")),
            "rules": rules,
        }
        raw_payload = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw_payload.encode("utf-8")).hexdigest()

    def build_payload(self, record: dict) -> dict:
        """把详情记录转换为 worker 可执行的自动处理 payload。"""
        output_root = Path(str(record.get("_output_root") or "output")).expanduser()
        return {
            "applet_id": applet_cache_id(record),
            "packages_root": str(record.get("_packages_root") or ""),
            "output_root": str(output_root),
            "cache_path": str(self.cache_path(output_root)),
            "new_folders": record_new_folders(record),
            "optimize_enabled": bool(record.get("_optimize_code_enabled")),
            "rules": enabled_rules(record),
        }

    def ensure_record(self, record: dict) -> None:
        """在卡片生成时确保对应小程序已有后台自动处理任务或缓存。"""
        record_id = int(record.get("id") or 0)
        if record_id <= 0:
            return
        if not self.should_auto_process(record):
            self.pending_records.pop(record_id, None)
            self.pending_signatures.pop(record_id, None)
            self.cancel_record(record_id)
            return

        signature = self.request_signature(record)
        active_task_id = self.active_tasks.get(record_id)
        if active_task_id is not None and self.task_signatures.get(active_task_id) == signature:
            self.pending_records.pop(record_id, None)
            self.pending_signatures.pop(record_id, None)
            return
        if active_task_id is not None:
            self.defer_record_restart(record_id, record, signature)
            return

        snapshot = self.snapshots.get(record_id, {})
        if self.record_signatures.get(record_id) == signature and snapshot.get("status") in {"done", "running", "skipped"}:
            return

        self.submit_record(record, signature)

    def defer_record_restart(self, record_id: int, record: dict, signature: str) -> None:
        """运行中记录发生合并变化时短暂防抖，避免连续取消和重启反编译。"""
        self.pending_records[record_id] = dict(record)
        self.pending_signatures[record_id] = str(signature)
        snapshot = copy.deepcopy(self.snapshots.get(record_id, {}))
        snapshot.update(
            {
                "status": "running",
                "stage": "debounced",
                "message": "检测到小程序包变化，等待合并后继续自动处理",
                "_request_signature": self.record_signatures.get(record_id, signature),
                "_pending_request_signature": signature,
            }
        )
        self.snapshots[record_id] = snapshot
        self.emit_processing_update(record_id, snapshot)
        self.schedule_pending_flush()

    def emit_processing_update(self, record_id: int, snapshot: dict) -> None:
        """安全发送处理状态，测试替身未初始化 QObject 时直接跳过信号。"""
        try:
            self.processing_updated.emit(record_id, copy.deepcopy(compact_processing_state(snapshot)))
        except RuntimeError:
            return

    def schedule_pending_flush(self) -> None:
        """启动或重置待处理记录防抖定时器。"""
        self.restart_timer.start(AUTO_PROCESS_RESTART_DEBOUNCE_MS)

    def flush_pending_records(self) -> None:
        """提交防抖后仍需处理的记录。"""
        pending_records = self.pending_records
        pending_signatures = self.pending_signatures
        self.pending_records = {}
        self.pending_signatures = {}
        for record_id, record in pending_records.items():
            if not self.should_auto_process(record):
                self.cancel_record(record_id)
                continue
            signature = pending_signatures.get(record_id) or self.request_signature(record)
            active_task_id = self.active_tasks.get(record_id)
            if active_task_id is not None and self.task_signatures.get(active_task_id) == signature:
                continue
            snapshot = self.snapshots.get(record_id, {})
            if (
                active_task_id is None
                and self.record_signatures.get(record_id) == signature
                and snapshot.get("status") in {"done", "running", "skipped"}
            ):
                continue
            self.submit_record(record, signature)

    def submit_record(self, record: dict, signature: str) -> None:
        """立即提交自动处理任务，并在必要时取消旧任务。"""
        record_id = int(record.get("id") or 0)
        if record_id <= 0:
            return
        active_task_id = self.active_tasks.get(record_id)
        if active_task_id is not None:
            self.ensure_runner().cancel(active_task_id)
            self.active_tasks.pop(record_id, None)
            self.task_records.pop(active_task_id, None)
            self.task_signatures.pop(active_task_id, None)

        payload = self.build_payload(record)
        task_id = self.ensure_runner().submit("auto_process", payload)
        output_root = Path(str(payload.get("output_root") or "output")).expanduser()
        from package.decompiler.cache_keys import output_dirs_for_folders

        self.active_tasks[record_id] = task_id
        self.task_records[task_id] = record_id
        self.task_signatures[task_id] = signature
        self.record_signatures[record_id] = signature
        self.snapshots[record_id] = {
            "applet_id": str(payload.get("applet_id") or ""),
            "cache_path": str(payload.get("cache_path") or ""),
            "output_dirs": [str(path) for path in output_dirs_for_folders(output_root, record_new_folders(record))],
            "status": "running",
            "stage": "queued",
            "message": "后台自动处理已排队",
            "_request_signature": signature,
        }
        self.emit_processing_update(record_id, self.snapshots[record_id])

    def cancel_record(self, record_id: int) -> None:
        """取消指定小程序仍在运行的自动处理任务。"""
        self.pending_records.pop(record_id, None)
        self.pending_signatures.pop(record_id, None)
        task_id = self.active_tasks.get(record_id)
        if task_id is None:
            return
        self.ensure_runner().cancel(task_id)
        self.snapshots[record_id] = {"status": "cancelling", "message": "自动处理取消中"}
        self.emit_processing_update(record_id, self.snapshots[record_id])

    def delete_record(self, record: dict) -> None:
        """兼容旧入口：删除记录时只撤销任务并清空本地状态。"""
        record_id = int(record.get("id") or 0)
        if record_id <= 0:
            return
        self.forget_record(record_id)

    def forget_record(self, record_id: int) -> None:
        """删除记录时只清理内存态，真正磁盘删除交给后台监控 worker。"""
        task_id = self.active_tasks.pop(record_id, None)
        if task_id is not None and self.runner is not None:
            self.runner.cancel(task_id)
        if task_id is not None:
            self.task_records.pop(task_id, None)
            self.task_signatures.pop(task_id, None)
        self.pending_records.pop(record_id, None)
        self.pending_signatures.pop(record_id, None)
        self.record_signatures.pop(record_id, None)
        self.snapshots.pop(record_id, None)

    def snapshot(self, record_id: int) -> dict:
        """返回指定小程序的最新自动处理状态快照。"""
        return copy.deepcopy(compact_processing_state(self.snapshots.get(int(record_id or 0), {})))

    def process_events(self) -> None:
        """从后台 worker 队列非阻塞消费自动处理事件。"""
        if self.runner is None:
            return
        for _index in range(AUTO_PROCESS_EVENT_BATCH_LIMIT):
            try:
                event = self.runner.get_event_nowait()
            except queue.Empty:
                break
            self.handle_event(event)

    def handle_event(self, event: dict) -> None:
        """按事件类型更新本地状态并通知主窗口刷新展示。"""
        task_id = int(event.get("task_id") or 0)
        record_id = self.task_records.get(task_id)
        if record_id is None:
            applet_id = str(event.get("applet_id") or "").strip()
            record_id = int(applet_id) if applet_id.isdigit() else 0
        if record_id <= 0:
            return

        event_type = str(event.get("type") or "")
        if event_type == "auto_process_started":
            self.update_running_snapshot(record_id, task_id, "started", str(event.get("message") or "自动处理已启动"))
            return
        if event_type == "auto_process_stage":
            entry = event.get("entry") if isinstance(event.get("entry"), dict) else None
            self.update_running_snapshot(record_id, task_id, str(event.get("stage") or ""), str(event.get("message") or ""), entry)
            return
        if event_type == "auto_process_result":
            self.finish_record(record_id, task_id, event.get("entry") if isinstance(event.get("entry"), dict) else {})
            return
        if event_type == "auto_process_error":
            self.fail_record(record_id, task_id, str(event.get("message") or "自动处理失败"))
            return
        if event_type == "auto_process_cancelled":
            self.fail_record(record_id, task_id, "自动处理已取消", status="cancelled")

    def update_running_snapshot(
        self,
        record_id: int,
        task_id: int,
        stage: str,
        message: str,
        entry: dict | None = None,
    ) -> None:
        """保存运行中状态并通知界面刷新。"""
        signature = self.task_signatures.get(task_id, self.record_signatures.get(record_id, ""))
        snapshot = compact_processing_state(entry) if isinstance(entry, dict) else copy.deepcopy(self.snapshots.get(record_id, {}))
        snapshot.update(
            {
                "status": "running",
                "stage": stage,
                "message": message or snapshot.get("message") or "后台自动处理中",
                "_request_signature": signature,
            }
        )
        self.snapshots[record_id] = snapshot
        self.emit_processing_update(record_id, snapshot)

    def finish_record(self, record_id: int, task_id: int, entry: dict) -> None:
        """保存完成状态并清理任务映射。"""
        signature = self.task_signatures.get(task_id, self.record_signatures.get(record_id, ""))
        snapshot = compact_processing_state(entry)
        snapshot.setdefault("status", "done")
        snapshot.setdefault("message", "自动处理完成")
        snapshot["_request_signature"] = signature
        self.snapshots[record_id] = snapshot
        self.active_tasks.pop(record_id, None)
        self.task_records.pop(task_id, None)
        self.task_signatures.pop(task_id, None)
        self.emit_processing_update(record_id, snapshot)

    def fail_record(self, record_id: int, task_id: int, message: str, status: str = "error") -> None:
        """保存失败或取消状态，避免单任务异常影响主程序。"""
        signature = self.task_signatures.get(task_id, self.record_signatures.get(record_id, ""))
        snapshot = {
            "status": status,
            "message": message,
            "_request_signature": signature,
        }
        self.snapshots[record_id] = snapshot
        self.active_tasks.pop(record_id, None)
        self.task_records.pop(task_id, None)
        self.task_signatures.pop(task_id, None)
        self.emit_processing_update(record_id, snapshot)

    def shutdown(self) -> None:
        """停止自动处理调度器和后台 worker 进程。"""
        if self.closed:
            return
        self.closed = True
        self.event_timer.stop()
        self.restart_timer.stop()
        if self.runner is not None:
            for task_id in list(self.active_tasks.values()):
                self.runner.cancel(task_id)
        self.active_tasks.clear()
        self.task_records.clear()
        self.task_signatures.clear()
        if self.runner is not None:
            self.runner.shutdown(wait=False)
            self.runner = None
