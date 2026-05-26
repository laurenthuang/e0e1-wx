"""实现主窗口初始化、配置入口、详情页联动和关闭清理。"""
from __future__ import annotations

import multiprocessing as mp
import time
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from package.applet_logs import LogStore
from package.applet_routes.service import RouteService
from package.applet_processing import AppletAutoProcessManager
from package.config.defaults import DEFAULT_APPLET_PACKAGES_PATH
from package.devtools.service import DevtoolsService
from package.js_injection.service import JsInjectionCatalogService
from package.mcp_control import McpControlService
from package.runtime import TaskSupervisor, UiLatencyTracker
from package.storage.state_store import StateStore
from package.ui.cards import MonitorCardGridController, MonitorRecordStore
from package.ui.config_dialog import ConfigDialog
from package.ui.constants import MONITOR_RECORDS_COALESCE_MS, STARTUP_SERVICES_DELAY_MS, UI_EVENT_POLL_INTERVAL_MS
from package.ui.crypto_dialog import CryptoDialog
from package.ui.main_window_controls import MainWindowControlsMixin
from package.ui.main_window_monitor import MainWindowMonitorMixin
from package.ui.paths import config_path, output_root_path as default_output_root_path
from package.ui.rules_dialog import RegexRulesDialog
from package.ui.window_chrome import ChromeMainWindow
from package.ui.widgets import MiniProgramCard, ModuleButton

if TYPE_CHECKING:
    from package.applet_detail import AppletDetailWindow
    from package.monitor.controller import MiniProgramMonitor


class MainWindow(MainWindowControlsMixin, MainWindowMonitorMixin, ChromeMainWindow):
    def __init__(self) -> None:
        """初始化主窗口、事件队列和后台监控。"""
        super().__init__()
        self.ui_events: mp.Queue = mp.Queue()
        self.store = StateStore(config_path(), self.ui_events, start_worker=False)
        self.module_buttons: dict[str, ModuleButton] = {}
        self.monitor: MiniProgramMonitor | None = None
        self.monitor_id = 0
        self.monitor_root_path: Path | None = None
        self.monitor_records: list[dict] = []
        self.pending_monitor_records: list[dict] | None = None
        self.current_page = 0
        self.empty_state_label: QLabel | None = None
        self.detail_windows: dict[int, AppletDetailWindow] = {}
        self.task_supervisor = TaskSupervisor()
        self.ui_metrics = UiLatencyTracker()
        self.monitor_record_store = MonitorRecordStore()
        self.log_store = LogStore()
        self.devtools_service = DevtoolsService(self)
        self.devtools_service.state_changed.connect(self.on_devtools_state_logged)
        self.devtools_service.route_state_changed.connect(self.on_route_state_logged)
        self.devtools_service.miniapp_jump_state_changed.connect(self.on_miniapp_jump_state_logged)
        self.devtools_service.debug_toggle_log_emitted.connect(self.on_debug_toggle_log_logged)
        self.devtools_service.cloud_state_changed.connect(self.on_cloud_state_logged)
        self.devtools_service.cloud_calls_changed.connect(self.on_cloud_calls_logged)
        self.devtools_service.cloud_call_completed.connect(self.on_cloud_call_completed_logged)
        self.devtools_service.cloud_static_scan_completed.connect(self.on_cloud_static_scan_completed_logged)
        self.devtools_service.cloud_static_scan_failed.connect(self.on_cloud_static_scan_failed_logged)
        self.devtools_service.js_injection_state_changed.connect(self.on_js_injection_state_logged)
        self.devtools_service.state_changed.connect(self.on_js_injection_devtools_state_changed)
        self.js_injection_service = JsInjectionCatalogService(self)
        self.js_injection_service.catalog_changed.connect(self.on_js_catalog_changed)
        self.js_injection_service.catalog_error.connect(self.on_js_catalog_error)
        self.mcp_service = McpControlService(self)
        self.route_service = RouteService(self.devtools_service, self)
        self.auto_processor = AppletAutoProcessManager(self)
        self.auto_processor.processing_updated.connect(self.on_auto_processing_updated)

        self.setWindowTitle("微信小程序自动化监控")
        self.title_bar.set_subtitle("e0e1-wx-gui 1.4  https://github.com/eeeeeeeeee-code/e0e1-wx")
        self.resize(1180, 760)
        self.setMinimumSize(980, 640)

        central = QWidget()
        central.setObjectName("MainWindowRoot")
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(16)

        root.addWidget(self.build_control_panel())
        self.monitor_panel = self.build_monitor_panel()
        self.monitor_grid = MonitorCardGridController(self.cards_layout, MiniProgramCard)
        self.monitor_records_timer = QTimer(self)
        self.monitor_records_timer.setSingleShot(True)
        self.monitor_records_timer.setInterval(MONITOR_RECORDS_COALESCE_MS)
        self.monitor_records_timer.timeout.connect(self.flush_pending_monitor_records)
        root.addWidget(self.monitor_panel, 1)

        self.refresh_module_buttons()
        self.refresh_monitor_cards()
        self.refresh_state_hint()
        self._startup_services_started = False
        self._state_dependent_services_started = False

        self.event_timer = QTimer(self)
        self.event_timer.timeout.connect(self.process_ui_events)
        self.event_timer.start(UI_EVENT_POLL_INTERVAL_MS)
        QTimer.singleShot(STARTUP_SERVICES_DELAY_MS, self.start_startup_services)

    def start_startup_services(self) -> None:
        """在主窗口首帧显示后启动后台服务，避免启动期子进程抢在界面前闪现。"""
        if self._startup_services_started:
            return
        self._startup_services_started = True
        self.store.start_worker()
        if getattr(self.store, "loaded", False):
            self.start_state_dependent_services()

    def output_root_path(self) -> Path:
        """返回小程序反编译输出根目录。"""
        return default_output_root_path()

    def measure_ui_block(self, name: str, callback) -> None:
        """记录主线程关键路径耗时。"""
        started = time.perf_counter()
        callback()
        self.ui_metrics.record(name, (time.perf_counter() - started) * 1000.0)

    def open_regex_dialog(self) -> None:
        """打开正则规则配置窗口。"""
        dialog = RegexRulesDialog(self.store.snapshot()["rules"], self)
        dialog.rules_saved.connect(self.update_rules)
        dialog.exec()

    def update_rules(self, rules: list[dict]) -> None:
        """接收并保存正则规则列表。"""
        self.store.update_rules(rules)
        self.schedule_visible_auto_processing()
        self.refresh_open_detail_record()

    def current_config(self) -> dict:
        """返回当前配置快照。"""
        return dict(self.store.state.get("config", {}))

    def applet_packages_path(self) -> Path:
        """获取当前配置中的微信小程序 packages 路径。"""
        config = self.store.state.get("config", {})
        raw_path = str(config.get("applet_packages_path", DEFAULT_APPLET_PACKAGES_PATH)).strip()
        return Path(raw_path or DEFAULT_APPLET_PACKAGES_PATH).expanduser()

    def open_config_dialog(self) -> None:
        """打开 Config 配置窗口并在关闭后重启监控。"""
        dialog = ConfigDialog(self.store, self)
        dialog.exec()
        self.restart_monitor()
        self.refresh_open_detail_record()

    def open_crypto_dialog(self) -> None:
        """打开微信加密解密窗口。"""
        dialog = CryptoDialog(self)
        dialog.exec()

    def open_js_injection_dialog(self) -> None:
        """打开 JS 文件注入配置窗口。"""
        from package.js_injection import JsInjectionDialog

        self.refresh_js_catalog()
        dialog = JsInjectionDialog(
            self.js_injection_service,
            self.devtools_service,
            auto_enabled_getter=self.js_auto_enabled_map,
            runtime_toggle_enabled_getter=self.js_runtime_toggle_override_map,
            on_auto_changed=self.update_js_auto_enabled,
            on_runtime_toggle_changed=self.update_js_runtime_toggle_override,
            on_import_requested=self.import_js_file_path,
            on_remove_requested=getattr(self, "remove_js_script", None),
            parent=self,
        )
        dialog.exec()

    def open_mcp_dialog(self) -> None:
        """打开 MCP 后台服务控制窗口。"""
        from package.ui.mcp_dialog import McpDialog

        dialog = McpDialog(self.mcp_service, self)
        dialog.exec()

    def closeEvent(self, event) -> None:
        """窗口关闭时保存状态并停止后台任务。"""
        for window in list(self.detail_windows.values()):
            window.close()
        self.detail_windows.clear()
        self.mcp_service.shutdown()
        self.route_service.shutdown()
        self.devtools_service.shutdown()
        self.js_injection_service.shutdown()
        self.store.save()
        self.auto_processor.shutdown()
        self.stop_monitor(wait=False)
        self.store.shutdown()
        super().closeEvent(event)
