"""异步读写应用状态文件，并管理功能开关、配置和规则。"""

from __future__ import annotations

import asyncio
import copy
import json
import multiprocessing as mp
import queue
from pathlib import Path

from package.applet_logs import normalize_log_settings
from package.applet_detail.decompile_search_state import normalize_global_search_state
from package.config.defaults import (
    DEFAULT_DEVTOOLS_CDP_PORT,
    DEFAULT_MINIAPP_DEBUG_PORT,
    DEFAULT_STATE,
    normalize_cloud_call_timeout,
    normalize_devtools_port,
    normalize_route_traverse_interval,
)
from package.js_injection.mode_overrides import coerce_runtime_toggle_override_value
from package.regex_rules import is_legacy_default_regex_rules


def js_script_id_for_path(path: str) -> str:
    """按需计算 JS 脚本 ID，避免启动时加载目录扫描模块。"""
    from package.js_injection.catalog import script_id_for_path

    return script_id_for_path(path)


def normalize_js_injection_state(raw_state) -> dict:
    """过滤并归一化 JS 注入配置段。"""
    result = {"imported_files": [], "auto_enabled": {}, "runtime_toggle_overrides": {}}
    if not isinstance(raw_state, dict):
        return result

    imported_files = raw_state.get("imported_files")
    if isinstance(imported_files, list):
        seen_paths: set[str] = set()
        for item in imported_files:
            path = str(item or "").strip()
            if not path or path in seen_paths:
                continue
            seen_paths.add(path)
            result["imported_files"].append(path)

    auto_enabled = raw_state.get("auto_enabled")
    if isinstance(auto_enabled, dict):
        for key, value in auto_enabled.items():
            script_id = str(key or "").strip()
            if not script_id:
                continue
            result["auto_enabled"][script_id] = bool(value)

    runtime_toggle_overrides = raw_state.get("runtime_toggle_overrides")
    if isinstance(runtime_toggle_overrides, dict):
        for key, value in runtime_toggle_overrides.items():
            script_id = str(key or "").strip()
            if not script_id:
                continue
            normalized_override = coerce_runtime_toggle_override_value(value)
            if normalized_override:
                result["runtime_toggle_overrides"][script_id] = normalized_override
    return result


def merge_state(raw_state: dict) -> dict:
    """合并磁盘状态与默认状态，过滤掉无效配置。"""
    state = copy.deepcopy(DEFAULT_STATE)
    if not isinstance(raw_state, dict):
        return state

    toggles = raw_state.get("toggles")
    if isinstance(toggles, dict):
        for key in state["toggles"]:
            state["toggles"][key] = bool(toggles.get(key, state["toggles"][key]))

    config = raw_state.get("config")
    if isinstance(config, dict):
        applet_packages_path = config.get("applet_packages_path")
        if applet_packages_path is not None:
            state["config"]["applet_packages_path"] = str(applet_packages_path).strip()
        state["config"]["cloud_call_timeout_seconds"] = normalize_cloud_call_timeout(
            config.get("cloud_call_timeout_seconds", state["config"].get("cloud_call_timeout_seconds"))
        )
        state["config"]["route_traverse_interval_seconds"] = normalize_route_traverse_interval(
            config.get(
                "route_traverse_interval_seconds",
                state["config"].get("route_traverse_interval_seconds"),
            )
        )
        state["config"]["miniapp_debug_port"] = normalize_devtools_port(
            config.get("miniapp_debug_port", state["config"].get("miniapp_debug_port")),
            DEFAULT_MINIAPP_DEBUG_PORT,
        )
        state["config"]["devtools_cdp_port"] = normalize_devtools_port(
            config.get("devtools_cdp_port", state["config"].get("devtools_cdp_port")),
            DEFAULT_DEVTOOLS_CDP_PORT,
        )

    rules = raw_state.get("rules")
    if isinstance(rules, list):
        valid_rules = []
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            name = str(rule.get("name", "")).strip()
            pattern = str(rule.get("pattern", "")).strip()
            if not name or not pattern:
                continue
            valid_rules.append(
                {
                    "name": name,
                    "pattern": pattern,
                    "enabled": bool(rule.get("enabled", True)),
                    "note": str(rule.get("note", "")).strip(),
                }
            )
        if valid_rules and not is_legacy_default_regex_rules(valid_rules):
            state["rules"] = valid_rules

    log_settings = raw_state.get("log_settings")
    if isinstance(log_settings, dict):
        records = log_settings.get("records")
        if isinstance(records, dict):
            valid_records = {}
            for key, settings in records.items():
                record_key = str(key or "").strip()
                if not record_key:
                    continue
                valid_records[record_key] = normalize_log_settings(settings)
            state["log_settings"]["records"] = valid_records

    global_search = raw_state.get("global_search")
    if isinstance(global_search, dict):
        records = global_search.get("records")
        if isinstance(records, dict):
            valid_records = {}
            for key, search_state in records.items():
                record_key = str(key or "").strip()
                if not record_key:
                    continue
                valid_records[record_key] = normalize_global_search_state(search_state)
            state["global_search"]["records"] = valid_records

    state["js_injection"] = normalize_js_injection_state(raw_state.get("js_injection"))

    return state


def load_from_disk(path: Path) -> dict:
    """在子进程中读取状态文件，失败时返回默认状态。"""
    if not path.exists():
        return copy.deepcopy(DEFAULT_STATE)
    try:
        with path.open("r", encoding="utf-8") as file:
            return merge_state(json.load(file))
    except (OSError, json.JSONDecodeError):
        return copy.deepcopy(DEFAULT_STATE)


def save_to_disk(path: Path, state: dict) -> None:
    """在子进程中保存状态文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(state, file, ensure_ascii=False, indent=2)


def save_merged_state_to_disk(path: Path, state: dict) -> None:
    """在线程中合并并保存状态，避免阻塞状态 worker 事件循环。"""
    save_to_disk(path, merge_state(state))


class AsyncStateWorker:
    """在独立进程中运行的 asyncio 状态读写 worker。"""

    def __init__(self, path: Path, event_queue: mp.Queue, command_queue: mp.Queue) -> None:
        """初始化状态 worker 的文件路径和进程队列。"""
        self.path = path
        self.event_queue = event_queue
        self.command_queue = command_queue
        self.running = True

    async def run(self) -> None:
        """运行状态加载和保存命令循环。"""
        try:
            state = await asyncio.to_thread(load_from_disk, self.path)
            self.event_queue.put({"type": "state_loaded", "state": state})
            while self.running:
                await self.process_commands()
                await asyncio.sleep(0.05)
        except Exception as exc:
            self.event_queue.put({"type": "error", "message": f"配置进程异常：{exc}"})

    async def process_commands(self) -> None:
        """处理 UI 进程发送的状态保存命令。"""
        latest_state: dict | None = None
        while True:
            try:
                command = self.command_queue.get_nowait()
            except queue.Empty:
                break

            command_type = command.get("type")
            if command_type == "stop":
                self.running = False
                break
            if command_type == "save":
                latest_state = command.get("state")

        if latest_state is not None:
            await asyncio.to_thread(save_merged_state_to_disk, self.path, latest_state)


def state_worker_main(path: str, event_queue: mp.Queue, command_queue: mp.Queue) -> None:
    """状态 worker 子进程入口。"""
    asyncio.run(AsyncStateWorker(Path(path), event_queue, command_queue).run())


class StateStore:
    """管理 UI 进程内状态快照，并把文件 IO 交给独立进程。"""

    def __init__(self, path: Path, event_queue: mp.Queue | None = None, *, start_worker: bool = True) -> None:
        """初始化状态仓库并启动状态 worker 进程。"""
        self.path = path
        self.event_queue = event_queue or mp.Queue()
        self.command_queue: mp.Queue = mp.Queue()
        self.state = copy.deepcopy(DEFAULT_STATE)
        self.loaded = False
        self.process = mp.Process(
            target=state_worker_main,
            args=(str(self.path), self.event_queue, self.command_queue),
            daemon=True,
            name="state-async-worker",
        )
        self._worker_started = False
        if start_worker:
            self.start_worker()

    def start_worker(self) -> None:
        """按需启动状态 worker 进程。"""
        if self._worker_started:
            return
        self.process.start()
        self._worker_started = True

    def handle_event(self, event: dict) -> bool:
        """接收状态 worker 发回的事件并返回状态是否发生变化。"""
        if event.get("type") != "state_loaded":
            return False

        next_state = merge_state(event.get("state", {}))
        self.loaded = True
        if next_state == self.state:
            return False

        self.state = next_state
        return True

    def snapshot(self) -> dict:
        """返回 UI 进程内的状态快照。"""
        return copy.deepcopy(self.state)

    def save(self) -> None:
        """把当前状态快照提交给状态 worker 保存。"""
        self.command_queue.put({"type": "save", "state": self.snapshot()})

    def update_config(self, key: str, value) -> None:
        """更新单项配置并提交异步保存。"""
        self.state.setdefault("config", {})
        self.state["config"][key] = value
        self.save()

    def update_toggle(self, key: str, value: bool) -> None:
        """更新模块开关状态并提交异步保存。"""
        self.state.setdefault("toggles", {})
        self.state["toggles"][key] = bool(value)
        self.save()

    def update_rules(self, rules: list[dict]) -> None:
        """更新正则规则列表并提交异步保存。"""
        self.state["rules"] = copy.deepcopy(rules)
        self.save()

    def update_log_settings(self, record_key: str, settings: dict) -> None:
        """更新指定小程序卡片的日志设置并提交异步保存。"""
        key = str(record_key or "").strip()
        if not key:
            return
        self.state.setdefault("log_settings", {})
        self.state["log_settings"].setdefault("records", {})
        self.state["log_settings"]["records"][key] = normalize_log_settings(settings)
        self.save()

    def update_global_search_state(self, record_key: str, state: dict) -> None:
        """更新指定小程序卡片的全局搜索状态并提交异步保存。"""
        key = str(record_key or "").strip()
        if not key:
            return
        self.state.setdefault("global_search", {})
        self.state["global_search"].setdefault("records", {})
        self.state["global_search"]["records"][key] = normalize_global_search_state(state)
        self.save()

    def js_imported_files(self) -> list[str]:
        """返回手工导入的 JS 文件路径列表。"""
        config = normalize_js_injection_state(self.state.get("js_injection"))
        return list(config["imported_files"])

    def js_auto_enabled_map(self) -> dict[str, bool]:
        """返回 JS 自动注入开关映射。"""
        config = normalize_js_injection_state(self.state.get("js_injection"))
        return dict(config["auto_enabled"])

    def js_runtime_toggle_override_map(self) -> dict[str, str]:
        """返回 JS 长期脚本覆盖开关映射。"""
        config = normalize_js_injection_state(self.state.get("js_injection"))
        return dict(config["runtime_toggle_overrides"])

    def update_js_imported_files(self, imported_files: list[str]) -> None:
        """更新手工导入 JS 文件列表并异步保存。"""
        normalized = normalize_js_injection_state(
            {
                "imported_files": imported_files,
                "auto_enabled": self.js_auto_enabled_map(),
                "runtime_toggle_overrides": self.js_runtime_toggle_override_map(),
            }
        )
        self.state.setdefault("js_injection", {})
        self.state["js_injection"]["imported_files"] = normalized["imported_files"]
        self.state["js_injection"]["auto_enabled"] = normalized["auto_enabled"]
        self.state["js_injection"]["runtime_toggle_overrides"] = normalized["runtime_toggle_overrides"]
        self.save()

    def update_js_auto_enabled(self, script_id: str, enabled: bool) -> None:
        """更新单个 JS 文件的自动注入开关并异步保存。"""
        key = str(script_id or "").strip()
        if not key:
            return
        self.state.setdefault("js_injection", {})
        self.state["js_injection"].setdefault("imported_files", [])
        self.state["js_injection"].setdefault("auto_enabled", {})
        self.state["js_injection"].setdefault("runtime_toggle_overrides", {})
        self.state["js_injection"]["auto_enabled"][key] = bool(enabled)
        self.save()

    def update_js_runtime_toggle_override(self, script_id: str, enabled) -> None:
        """更新单个 JS 文件的长期脚本开关并异步保存。"""
        key = str(script_id or "").strip()
        if not key:
            return
        normalized_override = coerce_runtime_toggle_override_value(enabled)
        self.state.setdefault("js_injection", {})
        self.state["js_injection"].setdefault("imported_files", [])
        self.state["js_injection"].setdefault("auto_enabled", {})
        self.state["js_injection"].setdefault("runtime_toggle_overrides", {})
        if normalized_override:
            self.state["js_injection"]["runtime_toggle_overrides"][key] = normalized_override
        else:
            self.state["js_injection"]["runtime_toggle_overrides"].pop(key, None)
        self.save()

    def add_js_imported_file(self, path: str) -> None:
        """追加一个手工导入 JS 文件路径并异步保存。"""
        raw_path = str(path or "").strip()
        if not raw_path:
            return
        imported_files = self.js_imported_files()
        existing_ids = {js_script_id_for_path(item) for item in imported_files}
        if js_script_id_for_path(raw_path) not in existing_ids:
            imported_files.append(raw_path)
        self.update_js_imported_files(imported_files)

    def remove_js_imported_script(self, script_id: str) -> None:
        """按脚本 ID 删除导入脚本及其关联配置。"""
        target_id = str(script_id or "").strip()
        if not target_id:
            return
        config = normalize_js_injection_state(self.state.get("js_injection"))
        kept_files = [path for path in config["imported_files"] if js_script_id_for_path(path) != target_id]
        auto_enabled = {key: value for key, value in config["auto_enabled"].items() if key != target_id}
        runtime_toggle_overrides = {
            key: value for key, value in config["runtime_toggle_overrides"].items() if key != target_id
        }
        self.state.setdefault("js_injection", {})
        self.state["js_injection"]["imported_files"] = kept_files
        self.state["js_injection"]["auto_enabled"] = auto_enabled
        self.state["js_injection"]["runtime_toggle_overrides"] = runtime_toggle_overrides
        self.save()

    def shutdown(self, wait: bool = False) -> None:
        """停止状态 worker 进程。"""
        if self.process.is_alive():
            self.command_queue.put({"type": "stop"})
            if not wait:
                return
            self.process.join(timeout=1.0)
        if self.process.is_alive():
            self.process.terminate()
            self.process.join(timeout=1.0)
