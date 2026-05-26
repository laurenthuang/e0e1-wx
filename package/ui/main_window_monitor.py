"""处理主窗口监控卡片列表、分页、UI 事件和详情窗口联动。"""

from __future__ import annotations

import queue

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QGridLayout, QLabel

from package.applet_detail.decompile_search_state import normalize_global_search_state
from package.applet_logs import (
    LogEntry,
    build_call_result_message,
    log_entry_from_state,
    log_record_key,
    normalize_log_settings,
)
from package.config.defaults import (
    DEFAULT_DEVTOOLS_CDP_PORT,
    DEFAULT_MINIAPP_DEBUG_PORT,
    normalize_cloud_call_timeout,
    normalize_devtools_port,
    normalize_route_traverse_interval,
)
from package.monitor.constants import PAGE_SIZE
from package.js_injection.models import is_runtime_toggle_script
from package.ui.cards.batch_delete import closed_record_ids
from package.ui.confirm_dialog import ask_danger_confirmation
from package.ui.constants import CARD_COLUMNS, CARD_COLUMN_SPACING, UI_EVENT_BATCH_LIMIT
from package.ui.paths import wxid_db_path
from package.ui.widgets import MiniProgramCard


class MainWindowMonitorMixin:
    def clear_layout(self, layout: QGridLayout) -> None:
        """清空网格布局中的旧控件。"""
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def refresh_monitor_cards(self) -> None:
        """按当前页记录增量刷新小程序卡片。"""
        records = self.monitor_records
        total_pages = max(1, (len(records) + PAGE_SIZE - 1) // PAGE_SIZE)
        if self.current_page >= total_pages:
            self.current_page = total_pages - 1

        if not records:
            self.monitor_grid.clear()
            if self.empty_state_label is None:
                self.empty_state_label = QLabel("当前未检测到小程序实例")
                self.empty_state_label.setObjectName("MutedLabel")
                self.empty_state_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self.empty_state_label.setMinimumHeight(180)
                self.cards_layout.addWidget(self.empty_state_label, 0, 0)
            self.update_pagination_controls()
            self.refresh_batch_delete_button()
            self.refresh_state_hint()
            return

        if self.empty_state_label is not None:
            self.cards_layout.removeWidget(self.empty_state_label)
            self.empty_state_label.deleteLater()
            self.empty_state_label = None

        page_start = self.current_page * PAGE_SIZE
        page_records = records[page_start : page_start + PAGE_SIZE]
        card_width = self.monitor_card_width()

        new_cards = self.monitor_grid.apply_page_records(page_records, card_width, CARD_COLUMNS)
        for card in new_cards:
            card.delete_requested.connect(self.delete_monitor_record)
            card.rebind_requested.connect(self.rebind_monitor_record)
            card.detail_requested.connect(self.open_applet_detail)

        for column in range(CARD_COLUMNS):
            self.cards_layout.setColumnStretch(column, 1)
        self.cards_layout.setRowStretch((len(page_records) + CARD_COLUMNS - 1) // CARD_COLUMNS, 1)
        self.update_pagination_controls()
        self.refresh_batch_delete_button()
        self.refresh_state_hint()

    def monitor_card_width(self) -> int:
        """根据监控区域可用宽度计算每张卡片的平均宽度。"""
        available_width = max(1, self.scroll_area.viewport().width())
        total_spacing = CARD_COLUMN_SPACING * (CARD_COLUMNS - 1)
        return max(1, (available_width - total_spacing) // CARD_COLUMNS)

    def resize_monitor_cards(self) -> None:
        """窗口尺寸变化时强制同步所有卡片为平均宽度。"""
        if not hasattr(self, "scroll_area"):
            return
        card_width = self.monitor_card_width()
        for card in self.card_container.findChildren(MiniProgramCard):
            card.set_equal_width(card_width)

    def resizeEvent(self, event) -> None:
        """主窗口尺寸变化时重新平均卡片宽度。"""
        super().resizeEvent(event)
        QTimer.singleShot(0, self.resize_monitor_cards)

    def update_pagination_controls(self) -> None:
        """刷新分页按钮和页码状态。"""
        total_pages = max(1, (len(self.monitor_records) + PAGE_SIZE - 1) // PAGE_SIZE)
        self.page_label.setText(f"{self.current_page + 1} / {total_pages}")
        self.prev_page_button.setEnabled(self.current_page > 0)
        self.next_page_button.setEnabled(self.current_page < total_pages - 1)

    def previous_page(self) -> None:
        """切换到上一页小程序卡片。"""
        if self.current_page > 0:
            self.current_page -= 1
            self.refresh_monitor_cards()

    def next_page(self) -> None:
        """切换到下一页小程序卡片。"""
        total_pages = max(1, (len(self.monitor_records) + PAGE_SIZE - 1) // PAGE_SIZE)
        if self.current_page < total_pages - 1:
            self.current_page += 1
            self.refresh_monitor_cards()

    def process_ui_events(self) -> None:
        """从进程安全队列中消费后台事件并更新 UI。"""
        for _index in range(UI_EVENT_BATCH_LIMIT):
            try:
                event = self.ui_events.get_nowait()
            except queue.Empty:
                break
            event_type = event.get("type")
            if event_type == "state_loaded":
                was_loaded = bool(getattr(self.store, "loaded", True))
                changed = self.store.handle_event(event)
                first_load = not was_loaded and bool(getattr(self.store, "loaded", False))
                if changed:
                    self.refresh_module_buttons()
                    self.refresh_state_hint()
                    if bool(getattr(self, "_state_dependent_services_started", True)):
                        self.refresh_js_catalog()
                        self.restart_monitor()
                if first_load:
                    self.start_state_dependent_services()
            elif event_type == "monitor_records":
                if event.get("monitor_id") != self.monitor_id:
                    continue
                records = event.get("records", [])
                if records == self.monitor_records and self.pending_monitor_records is None:
                    continue
                self.queue_monitor_records(records)
            elif event_type in {"warning", "error"}:
                if "monitor_id" in event and event.get("monitor_id") != self.monitor_id:
                    continue
                message = str(event.get("message", ""))
                if hasattr(self, "monitor_status_label"):
                    self.monitor_status_label.setText(message)
            elif event_type == "info":
                if hasattr(self, "monitor_status_label"):
                    self.monitor_status_label.setText(str(event.get("message", "")))

    def start_monitor(self) -> None:
        """启动或复用小程序后台监控进程。"""
        from package.monitor.controller import MiniProgramMonitor

        root_path = self.applet_packages_path()
        if self.monitor is not None and self.monitor_root_path == root_path:
            return
        self.stop_monitor(wait=False)
        self.monitor_root_path = root_path
        self.monitor_id += 1
        self.monitor = MiniProgramMonitor(root_path, wxid_db_path(), self.ui_events, self.monitor_id)
        self.monitor.start()
        if hasattr(self, "monitor_status_label"):
            self.monitor_status_label.setText("监控运行中")

    def stop_monitor(self, wait: bool = False) -> None:
        """请求停止当前小程序后台监控进程。"""
        if self.monitor is not None:
            self.monitor.stop()
            if wait:
                self.monitor.join(timeout=1.5)
                if self.monitor.is_alive():
                    self.monitor.terminate()
            self.monitor = None

    def restart_monitor(self) -> None:
        """重启小程序后台监控进程。"""
        self.start_monitor()

    def start_state_dependent_services(self) -> None:
        """状态文件加载完成后再启动依赖配置的后台服务。"""
        if bool(getattr(self, "_state_dependent_services_started", False)):
            return
        self._state_dependent_services_started = True
        self.refresh_js_catalog()
        self.start_monitor()

    def queue_monitor_records(self, records: list[dict]) -> None:
        """缓存最新一批监控记录，并启动短延迟合并刷新。"""
        self.pending_monitor_records = [dict(record) for record in records if isinstance(record, dict)]
        self.monitor_records_timer.start()

    def flush_pending_monitor_records(self) -> None:
        """应用最后一批监控记录，并触发增量 UI 刷新。"""
        if self.pending_monitor_records is None:
            return

        def apply_updates() -> None:
            """应用合并后的监控记录并刷新当前页卡片。"""
            records = self.pending_monitor_records or []
            self.pending_monitor_records = None
            diff = self.monitor_record_store.apply_records(records)
            self.monitor_records = records
            self.refresh_monitor_cards()
            touched_ids = diff.added_ids | diff.updated_ids
            for record in self.monitor_records:
                if int(record.get("id") or 0) in touched_ids:
                    self.schedule_card_auto_processing(record)
            self.refresh_open_detail_record()

        if hasattr(self, "measure_ui_block"):
            self.measure_ui_block("monitor_records_flush", apply_updates)
        else:
            apply_updates()

    def send_monitor_command(self, command_type: str, record_id: int, payload: dict | None = None) -> None:
        """向后台监控进程发送卡片操作命令。"""
        if self.monitor is None:
            return
        command = {"type": command_type, "id": record_id}
        if payload:
            command.update(payload)
        self.monitor.send_command(command)

    def delete_monitor_record(self, record_id: int) -> None:
        """确认后删除指定小程序数据库记录。"""
        confirmed = ask_danger_confirmation(
            self,
            title="删除记录",
            message="确认删除这条小程序记录？删除后会异步清理输出目录、包缓存和相关状态。",
            confirm_text="删除",
            cancel_text="取消",
        )
        if confirmed:
            def submit_delete() -> None:
                """投递单条删除命令并更新相关 UI 状态。"""
                window = self.detail_windows.get(record_id)
                if window is not None:
                    window.close()
                if hasattr(self, "auto_processor"):
                    self.auto_processor.forget_record(record_id)
                card = getattr(self, "monitor_grid", None)
                if card is not None and record_id in card.cards_by_id:
                    card.cards_by_id[record_id].set_busy(True, "删除中")
                self.send_monitor_command("delete", record_id, {"output_root": str(self.output_root_path())})

            if hasattr(self, "measure_ui_block"):
                self.measure_ui_block("delete_monitor_record", submit_delete)
            else:
                submit_delete()

    def delete_closed_monitor_records(self) -> None:
        """确认后批量删除全部已关闭的小程序卡片。"""
        record_ids = closed_record_ids(self.monitor_records)
        if not record_ids:
            if hasattr(self, "monitor_status_label"):
                self.monitor_status_label.setText("当前没有可批量删除的已关闭卡片")
            return
        confirmed = ask_danger_confirmation(
            self,
            title="批量删除已关闭卡片",
            message=f"确认删除 {len(record_ids)} 条已关闭小程序记录？删除后会异步清理输出目录、包缓存和相关状态。",
            confirm_text="批量删除",
            cancel_text="取消",
        )
        if not confirmed:
            return

        def submit_delete_many() -> None:
            """只做 UI 状态更新和命令投递，实际删除由监控 worker 执行。"""
            for record_id in record_ids:
                window = self.detail_windows.get(record_id)
                if window is not None:
                    window.close()
                if hasattr(self, "auto_processor"):
                    self.auto_processor.forget_record(record_id)
                grid = getattr(self, "monitor_grid", None)
                if grid is not None and record_id in grid.cards_by_id:
                    grid.cards_by_id[record_id].set_busy(True, "删除中")
            self.send_monitor_command(
                "delete_many",
                0,
                {"ids": record_ids, "output_root": str(self.output_root_path())},
            )
            if hasattr(self, "monitor_status_label"):
                self.monitor_status_label.setText(f"已提交 {len(record_ids)} 条已关闭记录删除任务")

        if hasattr(self, "measure_ui_block"):
            self.measure_ui_block("delete_closed_monitor_records", submit_delete_many)
        else:
            submit_delete_many()

    def hide_monitor_record(self, record_id: int) -> None:
        """隐藏指定小程序卡片。"""
        self.send_monitor_command("hide", record_id)

    def rebind_monitor_record(self, record_id: int) -> None:
        """请求后台重新绑定指定小程序记录。"""
        self.send_monitor_command("rebind", record_id)

    def open_applet_detail(self, record: dict) -> None:
        """为指定小程序卡片打开独立功能详情窗口。"""
        from package.applet_detail import AppletDetailWindow

        record_id = int(record.get("id") or 0)
        detail_record = self.prepare_detail_record(record)
        if record_id > 0 and record_id in self.detail_windows:
            window = self.detail_windows[record_id]
            window.update_record(detail_record)
            window.show()
            window.raise_()
            window.activateWindow()
            return

        window = AppletDetailWindow(
            detail_record,
            self,
            devtools_service=getattr(self, "devtools_service", None),
            route_service=getattr(self, "route_service", None),
            log_store=getattr(self, "log_store", None),
            js_injection_service=getattr(self, "js_injection_service", None),
            on_log_settings_changed=lambda settings, key=detail_record.get("_log_record_key", ""): self.update_log_settings(
                str(key), settings
            ),
            on_global_search_state_changed=lambda state, key=detail_record.get("_log_record_key", ""): self.update_global_search_state(
                str(key), state
            ),
        )
        window.closed.connect(self.remove_detail_window)
        if record_id > 0:
            self.detail_windows[record_id] = window
        window.show()

    def remove_detail_window(self, record_id: int) -> None:
        """详情窗口关闭后移除主窗口保存的引用。"""
        if record_id > 0:
            self.detail_windows.pop(record_id, None)

    def refresh_open_detail_record(self) -> None:
        """监控数据刷新时同步所有已打开的独立详情窗口。"""
        if not self.detail_windows:
            return
        records_by_id = {int(record.get("id") or 0): record for record in self.monitor_records}
        for record_id, window in list(self.detail_windows.items()):
            record = records_by_id.get(record_id)
            if record is not None:
                window.update_record(self.prepare_detail_record(record))

    def schedule_card_auto_processing(self, record: dict) -> None:
        """在小程序卡片生成时提交自动反编译流水线任务。"""
        self.auto_processor.ensure_record(self.prepare_detail_record(record))

    def schedule_visible_auto_processing(self) -> None:
        """重新调度当前可见卡片对应的自动处理任务。"""
        page_start = self.current_page * PAGE_SIZE
        for record in self.monitor_records[page_start : page_start + PAGE_SIZE]:
            self.schedule_card_auto_processing(record)

    def on_auto_processing_updated(self, record_id: int, _state: dict) -> None:
        """后台自动处理状态变化时刷新已打开详情页。"""
        state = dict(_state or {})
        state["record_id"] = int(record_id or state.get("record_id") or 0)
        self.append_feature_state_log("decompile_folder", state, "后台自动处理状态更新")
        window = self.detail_windows.get(int(record_id or 0))
        if window is None:
            return
        for record in self.monitor_records:
            if int(record.get("id") or 0) == int(record_id or 0):
                window.update_record(self.prepare_detail_record(record))
                return

    def prepare_detail_record(self, record: dict) -> dict:
        """为详情页补充反编译、代码优化、正则规则和输出路径。"""
        detail_record = dict(record)
        state = self.store.state
        toggles = state.get("toggles", {})
        detail_record["_decompile_enabled"] = bool(toggles.get("decompile", False))
        detail_record["_optimize_code_enabled"] = bool(toggles.get("optimize_code", False))
        detail_record["_cloud_enabled"] = bool(toggles.get("cloud", False))
        detail_record["_regex_rules"] = [dict(rule) for rule in state.get("rules", []) if isinstance(rule, dict)]
        detail_record["_packages_root"] = str(detail_record.get("packages_root") or "").strip() or str(self.applet_packages_path())
        detail_record["_output_root"] = str(self.output_root_path())
        detail_record["_cloud_call_timeout_seconds"] = normalize_cloud_call_timeout(
            state.get("config", {}).get("cloud_call_timeout_seconds")
        )
        detail_record["_route_traverse_interval_seconds"] = normalize_route_traverse_interval(
            state.get("config", {}).get("route_traverse_interval_seconds")
        )
        detail_record["_miniapp_debug_port"] = normalize_devtools_port(
            state.get("config", {}).get("miniapp_debug_port"),
            DEFAULT_MINIAPP_DEBUG_PORT,
        )
        detail_record["_devtools_cdp_port"] = normalize_devtools_port(
            state.get("config", {}).get("devtools_cdp_port"),
            DEFAULT_DEVTOOLS_CDP_PORT,
        )
        detail_record["_processing_state"] = self.auto_processor.snapshot(int(detail_record.get("id") or 0))
        log_key = log_record_key(detail_record)
        detail_record["_log_record_key"] = log_key
        detail_record["_log_settings"] = normalize_log_settings(
            state.get("log_settings", {}).get("records", {}).get(log_key, {})
        )
        detail_record["_global_search_state"] = normalize_global_search_state(
            state.get("global_search", {}).get("records", {}).get(log_key, {})
        )
        return detail_record

    def refresh_batch_delete_button(self) -> None:
        """根据已关闭卡片数量刷新批量删除按钮状态。"""
        button = getattr(self, "batch_delete_closed_button", None)
        if button is None:
            return
        count = len(closed_record_ids(self.monitor_records))
        button.setEnabled(count > 0)
        button.setText(f"批量删除已关闭({count})" if count else "批量删除已关闭")

    def update_log_settings(self, record_key: str, settings: dict) -> None:
        """保存指定小程序卡片的日志筛选设置。"""
        self.store.update_log_settings(record_key, settings)
        for record in self.monitor_records:
            detail_key = log_record_key(record)
            if detail_key == str(record_key):
                prepared = self.prepare_detail_record(record)
                window = self.detail_windows.get(int(prepared.get("id") or 0))
                if window is not None:
                    window.update_record(prepared)
                break

    def update_global_search_state(self, record_key: str, state: dict) -> None:
        """保存指定小程序卡片的全局搜索状态。"""
        self.store.update_global_search_state(record_key, state)
        for record in self.monitor_records:
            detail_key = log_record_key(record)
            if detail_key != str(record_key):
                continue
            prepared = self.prepare_detail_record(record)
            window = self.detail_windows.get(int(prepared.get("id") or 0))
            if window is not None:
                window.update_record(prepared)
            break

    def refresh_js_catalog(self) -> None:
        """请求 JS 注入目录服务刷新脚本列表。"""
        service = getattr(self, "js_injection_service", None)
        if service is not None and hasattr(service, "refresh"):
            service.refresh(
                self.store.js_imported_files(),
                self.store.js_runtime_toggle_override_map(),
            )

    def js_auto_enabled_map(self) -> dict[str, bool]:
        """返回 JS 自动注入开关映射。"""
        return self.store.js_auto_enabled_map()

    def js_runtime_toggle_override_map(self) -> dict[str, str]:
        """返回 JS 长期脚本覆盖开关映射。"""
        return self.store.js_runtime_toggle_override_map()

    def update_js_auto_enabled(self, script_id: str, enabled: bool) -> None:
        """保存 JS 自动注入开关并尝试调度当前会话。"""
        self.store.update_js_auto_enabled(script_id, enabled)
        self.try_auto_inject_js()

    def update_js_runtime_toggle_override(self, script_id: str, enabled: str) -> None:
        """保存单个脚本的长期脚本开关并刷新目录。"""
        self.store.update_js_runtime_toggle_override(script_id, enabled)
        self.refresh_js_catalog()
        self.sync_runtime_toggle_override_for_current_session(script_id, enabled)

    def current_devtools_state(self) -> dict:
        """返回当前 DevTools 会话快照。"""
        devtools_service = getattr(self, "devtools_service", None)
        if devtools_service is None or not hasattr(devtools_service, "snapshot"):
            return {}
        return dict(devtools_service.snapshot())

    def current_js_script_by_id(self, script_id: str) -> dict:
        """从当前脚本目录缓存中按脚本 ID 查找脚本。"""
        service = getattr(self, "js_injection_service", None)
        if service is None or not hasattr(service, "scripts"):
            return {}
        target_id = str(script_id or "").strip()
        for script in service.scripts():
            if str(script.get("id") or "").strip() == target_id:
                return dict(script)
        return {}

    def sync_runtime_toggle_override_for_current_session(self, script_id: str, override_mode: str) -> None:
        """把主页面长期脚本覆盖同步到当前会话，并按需要立即启用或取消。"""
        current_state = self.current_devtools_state()
        if int(current_state.get("record_id") or 0) <= 0:
            return
        devtools_service = getattr(self, "devtools_service", None)
        if devtools_service is None:
            return
        script = self.current_js_script_by_id(script_id)
        if not script:
            return
        runtime_payload = {**script, "mode": "runtime_toggle"}
        if str(override_mode or "").strip() == "runtime_toggle":
            if hasattr(devtools_service, "set_runtime_toggle_auto_restore_for_session"):
                devtools_service.set_runtime_toggle_auto_restore_for_session(current_state, runtime_payload, True)
            if str(current_state.get("status") or "") != "running" or not current_state.get("miniapp"):
                return
            if hasattr(devtools_service, "enable_runtime_js_script_for_session"):
                devtools_service.enable_runtime_js_script_for_session(current_state, runtime_payload)
            return
        if hasattr(devtools_service, "set_runtime_toggle_auto_restore_for_session"):
            devtools_service.set_runtime_toggle_auto_restore_for_session(current_state, runtime_payload, False)
        if str(current_state.get("status") or "") != "running" or not current_state.get("miniapp"):
            return
        if hasattr(devtools_service, "disable_runtime_js_script_for_session"):
            devtools_service.disable_runtime_js_script_for_session(current_state, runtime_payload)

    def import_js_file_path(self, file_path: str) -> None:
        """保存手工导入的 JS 文件路径并刷新目录。"""
        self.store.add_js_imported_file(file_path)
        self.refresh_js_catalog()

    def remove_js_script(self, script: dict) -> None:
        """删除一个导入脚本，并在需要时最佳努力取消长期注入。"""
        if not isinstance(script, dict):
            return
        script_id = str(script.get("id") or "").strip()
        if not script_id or str(script.get("source") or "").strip() != "imported":
            return
        self.store.remove_js_imported_script(script_id)
        if is_runtime_toggle_script(script):
            devtools_service = getattr(self, "devtools_service", None)
            if devtools_service is not None and hasattr(devtools_service, "disable_runtime_js_script"):
                current_state = devtools_service.snapshot() if hasattr(devtools_service, "snapshot") else {}
                record_id = int(current_state.get("record_id") or 0)
                if record_id > 0 and hasattr(devtools_service, "js_injection_states_for_record"):
                    states = devtools_service.js_injection_states_for_record(record_id)
                    current_script_state = states.get(script_id, {})
                    if bool(current_script_state.get("enabled")):
                        record = {
                            "id": record_id,
                            "owner_key": str(current_state.get("owner_key") or ""),
                            "display_name": str(current_state.get("display_name") or ""),
                        }
                        devtools_service.disable_runtime_js_script(record, script)
        self.refresh_js_catalog()

    def on_js_catalog_changed(self, _scripts: list) -> None:
        """脚本目录变化后尝试对当前已就绪会话执行自动注入。"""
        self.try_auto_inject_js()

    def on_js_catalog_error(self, message: str) -> None:
        """显示 JS 目录扫描错误。"""
        if hasattr(self, "monitor_status_label"):
            self.monitor_status_label.setText(str(message or "JS 文件扫描失败"))

    def on_js_injection_devtools_state_changed(self, state: dict) -> None:
        """DevTools 会话状态变化后触发自动 JS 注入检查。"""
        self.try_auto_inject_js(state)

    def ensure_runtime_toggle_auto_injection_cache(self) -> dict[tuple[int, str], int]:
        """返回长期脚本自动启用去重缓存。"""
        cache = getattr(self, "_runtime_toggle_auto_epochs", None)
        if not isinstance(cache, dict):
            cache = {}
            self._runtime_toggle_auto_epochs = cache
        return cache

    def try_auto_inject_js(self, state: dict | None = None) -> None:
        """当当前会话已就绪时调度所有开启自动注入的普通脚本。"""
        service = getattr(self, "js_injection_service", None)
        devtools_service = getattr(self, "devtools_service", None)
        if service is None or devtools_service is None:
            return
        current_state = dict(state or devtools_service.snapshot())
        if str(current_state.get("status") or "") != "running":
            return
        # CDP 注入命令通过小程序回连通道发送；devtools 字段仅表示外部 inspector 前端是否连接。
        if not current_state.get("miniapp"):
            return
        if int(current_state.get("record_id") or 0) <= 0:
            return
        auto_map = self.js_auto_enabled_map()
        for script in service.scripts():
            script_id = str(script.get("id") or "")
            if not script_id or not bool(auto_map.get(script_id)) or not bool(script.get("available", True)):
                continue
            if is_runtime_toggle_script(script):
                continue
            devtools_service.inject_js_script_for_session(current_state, script, automatic=True)

    def append_feature_state_log(self, source: str, state: dict, fallback_message: str = "", record_key: str | None = None) -> None:
        """把功能状态事件转换成日志并写入共享日志缓冲。"""
        entry = log_entry_from_state(source, state, fallback_message=fallback_message, record_key=record_key)
        if entry is None:
            return
        self.append_feature_log_entry(entry)

    def append_feature_log(self, record_key: str | int, source: str, level: str, message: str) -> None:
        """直接写入一条指定功能点的小程序日志。"""
        key = str(record_key or "").strip()
        text = str(message or "").strip()
        if not key or key == "0" or not text:
            return
        self.append_feature_log_entry(LogEntry(record_key=key, source=source, level=level, message=text))

    def append_feature_log_entry(self, entry: LogEntry) -> None:
        """保存日志条目并刷新当前打开的日志页。"""
        store = getattr(self, "log_store", None)
        if store is None:
            return
        store.append(entry)
        self.refresh_open_log_pages(entry.record_key)

    def refresh_open_log_pages(self, record_key: str) -> None:
        """刷新当前打开且属于指定小程序的日志 Tab。"""
        for window in list(getattr(self, "detail_windows", {}).values()):
            page = getattr(window, "page", None)
            if page is None:
                continue
            page_record_key = str(getattr(page, "record", {}).get("_log_record_key") or log_record_key(getattr(page, "record", {})))
            if page_record_key != str(record_key):
                continue
            logs_index = page.tab_index("logs") if hasattr(page, "tab_index") else -1
            if logs_index < 0 or page.tabs.currentIndex() != logs_index:
                continue
            host = page.tab_hosts.get(logs_index)
            layout = host.layout() if host is not None else None
            widget = layout.itemAt(0).widget() if layout is not None and layout.count() else None
            if widget is not None and hasattr(widget, "refresh_logs"):
                widget.refresh_logs()

    def on_devtools_state_logged(self, state: dict) -> None:
        """记录 devtools-cdp 状态变化日志。"""
        self.append_feature_state_log("devtools_cdp", state, "devtools-cdp 状态更新")

    def on_route_state_logged(self, record_id: int, state: dict) -> None:
        """记录小程序路由状态变化日志。"""
        route_state = dict(state or {})
        route_state["record_id"] = int(record_id or route_state.get("record_id") or 0)
        self.append_feature_state_log("routes", route_state, "路由状态更新")

    def on_miniapp_jump_state_logged(self, record_id: int, state: dict) -> None:
        """记录跨小程序跳转状态变化日志。"""
        jump_state = dict(state or {})
        jump_state["record_id"] = int(record_id or jump_state.get("record_id") or 0)
        self.append_feature_state_log("miniapp_jump", jump_state, "跨小程序跳转状态更新")

    def on_debug_toggle_log_logged(self, payload: dict) -> None:
        """记录调试开关详细链路日志。"""
        if not isinstance(payload, dict):
            return
        record_key = str(payload.get("record_id") or payload.get("owner_key") or "").strip()
        if not record_key or record_key == "0":
            return
        message = str(payload.get("message") or "").strip()
        if not message:
            return
        action_labels = {
            "detect": "检测调试状态",
            "enable": "开启调试",
            "disable": "关闭调试",
        }
        stage_labels = {
            "command_received": "收到命令",
            "prepare_runtime": "准备会话",
            "runtime_ready": "运行时就绪",
            "detect_result": "检测结果",
            "detect_failed": "检测失败",
            "set_enable_debug": "设置成功",
            "set_enable_debug_failed": "设置失败",
            "cancelled": "任务取消",
        }
        action_label = action_labels.get(str(payload.get("action") or "").strip(), "")
        stage_label = stage_labels.get(str(payload.get("stage") or "").strip(), "")
        prefix_parts = [part for part in (action_label, stage_label) if part]
        if prefix_parts:
            message = f"{' / '.join(prefix_parts)}：{message}"
        self.append_feature_log(record_key, "debug_toggle", str(payload.get("level") or "INFO"), message)

    def on_js_injection_state_logged(self, record_id: int, state: dict) -> None:
        """记录 JS 注入状态变化日志。"""
        payload = dict(state or {})
        payload["record_id"] = int(record_id or payload.get("record_id") or 0)
        script_name = str(payload.get("script_name") or "JS文件").strip()
        status = str(payload.get("status") or "").strip()
        if status == "injecting":
            payload["message"] = f"{script_name} 正在注入"
        elif status == "enabling":
            payload["message"] = f"{script_name} 启用中"
        elif status == "enabled":
            payload["message"] = f"{script_name} {payload.get('message') or '已启用（当前页面和后续页面）'}"
        elif status == "disabling":
            payload["message"] = f"{script_name} 取消中"
        elif status == "disabled":
            payload["message"] = f"{script_name} {payload.get('message') or '已取消'}"
        elif status == "success":
            payload["message"] = f"{script_name} {payload.get('message') or '注入成功'}"
            report_detail = str(payload.get("log") or "").strip()
            if report_detail:
                payload["message"] = f"{payload['message']}：{report_detail}"
        elif status == "failed":
            reason = str(payload.get("error") or payload.get("message") or "").strip()
            payload["message"] = f"{script_name} 注入失败：{reason}" if reason else f"{script_name} 注入失败"
        self.append_feature_state_log("js_injection", payload, "JS 注入状态更新")

    def on_cloud_state_logged(self, state: dict) -> None:
        """记录云函数状态变化日志。"""
        self.append_feature_state_log("cloud_functions", state, "云函数状态更新")

    def on_cloud_calls_logged(self, calls: list) -> None:
        """记录动态云函数捕获数量变化日志。"""
        state = getattr(getattr(self, "devtools_service", None), "cloud_state", {})
        record_id = int(state.get("record_id") or 0) if isinstance(state, dict) else 0
        if record_id <= 0 or not calls:
            return
        self.append_feature_log(record_id, "cloud_functions", "INFO", f"动态捕获云调用 {len(calls)} 条")

    def on_cloud_call_completed_logged(self, result: dict) -> None:
        """记录手动云函数调用结果日志。"""
        if not isinstance(result, dict):
            return
        record_id = int(result.get("record_id") or 0)
        message = build_call_result_message(
            result,
            fallback_message=f"手动调用 {str(result.get('name') or '云函数').strip()}",
        )
        level = "INFO" if bool(result.get("ok", result.get("status") == "success")) else "ERROR"
        self.append_feature_log(record_id, "cloud_functions", level, message)

    def on_cloud_static_scan_completed_logged(self, record_id: int, results: list) -> None:
        """记录运行时云函数静态扫描完成日志。"""
        count = len(results) if isinstance(results, list) else 0
        self.append_feature_log(record_id, "cloud_functions", "INFO", f"运行时静态扫描完成，发现 {count} 项")

    def on_cloud_static_scan_failed_logged(self, record_id: int, message: str) -> None:
        """记录运行时云函数静态扫描失败日志。"""
        self.append_feature_log(record_id, "cloud_functions", "ERROR", str(message or "运行时静态扫描失败"))
