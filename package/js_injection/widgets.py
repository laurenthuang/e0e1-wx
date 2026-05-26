"""JS 注入功能的主窗口弹窗和详情页列表组件。"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from package.js_injection.mode_overrides import SCRIPT_OVERRIDE_ONCE, SCRIPT_OVERRIDE_RUNTIME_TOGGLE
from package.js_injection.models import is_runtime_toggle_script
from package.ui.window_chrome import ChromeDialog


JS_INJECTION_ROW_HEIGHT = 56


class JsInjectionTableWidget(QWidget):
    """复用 JS 注入脚本列表，支持全局自动开关或卡片手工注入。"""

    def __init__(
        self,
        catalog_service=None,
        devtools_service=None,
        record: dict | None = None,
        *,
        manual_mode: bool = False,
        auto_enabled_getter: Callable[[], dict[str, bool]] | None = None,
        runtime_toggle_enabled_getter: Callable[[], dict[str, str]] | None = None,
        on_auto_changed: Callable[[str, bool], None] | None = None,
        on_runtime_toggle_changed: Callable[[str, str], None] | None = None,
        on_import_requested: Callable[[str], None] | None = None,
        on_remove_requested: Callable[[dict], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """初始化脚本表格并连接目录、状态信号。"""
        super().__init__(parent)
        self.catalog_service = catalog_service
        self.devtools_service = devtools_service
        self.record = dict(record or {})
        self.manual_mode = bool(manual_mode)
        self.auto_enabled_getter = auto_enabled_getter
        self.runtime_toggle_enabled_getter = runtime_toggle_enabled_getter
        self.on_auto_changed = on_auto_changed
        self.on_runtime_toggle_changed = on_runtime_toggle_changed
        self.on_import_requested = on_import_requested
        self.on_remove_requested = on_remove_requested

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        if not self.manual_mode:
            action_row = QHBoxLayout()
            action_row.setSpacing(8)
            self.import_button = QPushButton("导入 JS 文件")
            self.import_button.setProperty("variant", "primary")
            self.import_button.setProperty("size", "sm")
            self.import_button.clicked.connect(self.import_js_file)
            action_row.addWidget(self.import_button)

            self.refresh_button = QPushButton("刷新列表")
            self.refresh_button.setProperty("variant", "ghost")
            self.refresh_button.setProperty("size", "sm")
            self.refresh_button.clicked.connect(self.refresh_catalog)
            action_row.addWidget(self.refresh_button)
            action_row.addItem(QSpacerItem(10, 10, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))
            root.addLayout(action_row)

        self.hint_label = QLabel("自动扫描 tools/js 下的 .js 文件；手工导入只保存路径，读取和注入均由后台进程执行。")
        self.hint_label.setObjectName("HintText")
        self.hint_label.setWordWrap(True)
        root.addWidget(self.hint_label)

        self.table = QTableWidget(0, len(self.column_labels()))
        self.table.setHorizontalHeaderLabels(self.column_labels())
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setMinimumSectionSize(JS_INJECTION_ROW_HEIGHT)
        self.table.verticalHeader().setDefaultSectionSize(JS_INJECTION_ROW_HEIGHT)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 260)
        self.table.setColumnWidth(1, 130)
        if not self.manual_mode:
            self.table.setColumnWidth(2, 130)
            self.table.setColumnWidth(3, 100)
        root.addWidget(self.table, 1)

        if self.catalog_service is not None and hasattr(self.catalog_service, "catalog_changed"):
            self.catalog_service.catalog_changed.connect(self.handle_catalog_changed)
        if self.devtools_service is not None and hasattr(self.devtools_service, "js_injection_state_changed"):
            self.devtools_service.js_injection_state_changed.connect(self.handle_js_state_changed)
        if self.devtools_service is not None and hasattr(self.devtools_service, "state_changed"):
            self.devtools_service.state_changed.connect(self.handle_devtools_state_changed)

        self.refresh_table()

    def column_labels(self) -> list[str]:
        """返回当前模式下的表头。"""
        if self.manual_mode:
            return ["JS名称", "手工注入", "当前状态"]
        return ["JS名称", "自动化注入", "长期脚本", "操作"]

    def update_record(self, record: dict) -> None:
        """详情页记录刷新时同步当前小程序上下文。"""
        self.record = dict(record or {})
        self.refresh_table()

    def handle_catalog_changed(self, _scripts: list) -> None:
        """目录扫描结果变化时刷新表格。"""
        self.refresh_table()

    def handle_js_state_changed(self, _record_id: int, _state: dict) -> None:
        """JS 注入状态变化时刷新表格。"""
        self.refresh_table()

    def handle_devtools_state_changed(self, _state: dict) -> None:
        """DevTools 会话变化时刷新当前状态列。"""
        self.refresh_table()

    def scripts(self) -> list[dict]:
        """返回目录服务缓存的脚本列表。"""
        if self.catalog_service is not None and hasattr(self.catalog_service, "scripts"):
            return self.catalog_service.scripts()
        return []

    def auto_enabled_map(self) -> dict[str, bool]:
        """返回当前自动注入开关映射。"""
        if self.auto_enabled_getter is None:
            return {}
        return dict(self.auto_enabled_getter())

    def runtime_toggle_enabled_map(self) -> dict[str, str]:
        """返回当前长期脚本覆盖开关映射。"""
        if self.runtime_toggle_enabled_getter is None:
            return {}
        return dict(self.runtime_toggle_enabled_getter())

    def current_record_id(self) -> int:
        """返回当前状态列应读取的记录 ID。"""
        if self.manual_mode:
            return int(self.record.get("id") or 0)
        if self.devtools_service is not None and hasattr(self.devtools_service, "snapshot"):
            state = self.devtools_service.snapshot()
            return int(state.get("record_id") or 0)
        return 0

    def states_for_current_record(self) -> dict[str, dict]:
        """返回当前记录的 JS 注入状态映射。"""
        record_id = self.current_record_id()
        if record_id <= 0 or self.devtools_service is None:
            return {}
        if hasattr(self.devtools_service, "js_injection_states_for_record"):
            return self.devtools_service.js_injection_states_for_record(record_id)
        return {}

    def refresh_table(self) -> None:
        """从缓存刷新 JS 列表、开关和状态文本。"""
        scripts = self.scripts()
        auto_map = self.auto_enabled_map()
        runtime_toggle_map = self.runtime_toggle_enabled_map()
        states = self.states_for_current_record()
        self.table.clearContents()
        self.table.setRowCount(len(scripts))
        for row, script in enumerate(scripts):
            script_id = str(script.get("id") or "")
            name_item = QTableWidgetItem(str(script.get("name") or "JS文件"))
            name_item.setToolTip(str(script.get("path") or ""))
            self.table.setItem(row, 0, name_item)
            if self.manual_mode:
                self.table.setCellWidget(row, 1, self.build_manual_button(script, states.get(script_id, {})))
                status_item = QTableWidgetItem(self.status_text(script, states.get(script_id, {})))
                status_item.setToolTip(status_item.text())
                self.table.setItem(row, 2, status_item)
            else:
                self.table.setCellWidget(row, 1, self.build_auto_checkbox(script_id, auto_map.get(script_id, False), script))
                self.table.setCellWidget(
                    row,
                    2,
                    self.build_runtime_toggle_checkbox(script_id, runtime_toggle_map.get(script_id, False), script),
                )
                self.table.setCellWidget(row, 3, self.build_remove_button(script))
            self.table.setRowHeight(row, JS_INJECTION_ROW_HEIGHT)
        if not scripts:
            self.table.setRowCount(1)
            self.table.setItem(0, 0, QTableWidgetItem("暂无 JS 文件"))
            self.table.setItem(0, 1, QTableWidgetItem("-"))
            self.table.setItem(0, 2, QTableWidgetItem("-" if not self.manual_mode else "请将 .js 放入 tools/js 或手工导入"))
            if self.manual_mode:
                self.table.setItem(0, 2, QTableWidgetItem("请将 .js 放入 tools/js 或手工导入"))
            else:
                self.table.setItem(0, 3, QTableWidgetItem("请将 .js 放入 tools/js 或手工导入"))
            self.table.setRowHeight(0, JS_INJECTION_ROW_HEIGHT)

    def build_auto_checkbox(self, script_id: str, enabled: bool, script: dict) -> QCheckBox:
        """创建自动注入开关控件。"""
        checkbox = QCheckBox("开启")
        checkbox.setCursor(Qt.CursorShape.PointingHandCursor)
        checkbox.setChecked(bool(enabled))
        checkbox.setEnabled(bool(script.get("available", True)))
        checkbox.toggled.connect(lambda checked, key=script_id: self.set_auto_enabled(key, checked))
        return checkbox

    def build_runtime_toggle_checkbox(self, script_id: str, override_mode: str, script: dict) -> QCheckBox:
        """创建主页面长期脚本开关控件。"""
        checkbox = QCheckBox("长期")
        checkbox.setCursor(Qt.CursorShape.PointingHandCursor)
        declared_runtime_toggle = str(script.get("declared_mode") or "") == "runtime_toggle"
        checkbox.setChecked(is_runtime_toggle_script(script))
        checkbox.setEnabled(bool(script.get("available", True)))
        if declared_runtime_toggle and not is_runtime_toggle_script(script):
            checkbox.setToolTip("该脚本文件头默认是长期脚本，但当前已按普通脚本处理")
        elif declared_runtime_toggle:
            checkbox.setToolTip("该脚本文件头默认是长期脚本")
        checkbox.toggled.connect(
            lambda checked, key=script_id: self.set_runtime_toggle_enabled(
                key,
                SCRIPT_OVERRIDE_RUNTIME_TOGGLE if checked else SCRIPT_OVERRIDE_ONCE,
            )
        )
        return checkbox

    def build_remove_button(self, script: dict) -> QPushButton:
        """创建主页面脚本删除/内置标记按钮。"""
        source = str(script.get("source") or "").strip()
        button = QPushButton("删除" if source == "imported" else "内置")
        button.setProperty("size", "sm")
        button.setMinimumHeight(36)
        button.setEnabled(source == "imported")
        if source == "imported":
            button.clicked.connect(lambda _checked=False, payload=dict(script): self.remove_script(payload))
        return button

    def build_manual_button(self, script: dict, state: dict) -> QPushButton:
        """创建详情页中的脚本动作按钮。"""
        runtime_toggle = is_runtime_toggle_script(script)
        button = QPushButton()
        button.setProperty("variant", "primary")
        button.setProperty("size", "sm")
        button.setMinimumHeight(36)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        status = str(state.get("status") or "").strip()
        enabled = bool(state.get("enabled"))
        busy = status in {"injecting", "enabling", "disabling"}
        button.setEnabled(bool(script.get("available", True)) and not busy and self.devtools_service is not None)
        if runtime_toggle:
            button.setText("取消注入" if enabled and status != "disabled" else "启用")
            if enabled and status != "disabled":
                button.clicked.connect(lambda _checked=False, payload=dict(script): self.disable_runtime_script(payload))
            else:
                button.clicked.connect(lambda _checked=False, payload=dict(script): self.enable_runtime_script(payload))
            return button
        button.setText("手工注入")
        button.clicked.connect(lambda _checked=False, payload=dict(script): self.inject_script(payload))
        return button

    def status_text(self, script: dict, state: dict) -> str:
        """把脚本可用性和注入状态转换为中文状态文本。"""
        if not bool(script.get("available", True)):
            return str(script.get("message") or "读取失败")
        if is_runtime_toggle_script(script):
            status = str(state.get("status") or "").strip()
            if status == "enabling":
                return "启用中"
            if status == "enabled":
                return str(state.get("message") or "已启用（当前页面和后续页面）")
            if status == "disabling":
                return "取消中"
            if status == "disabled":
                return str(state.get("message") or "已取消")
            if status == "failed":
                reason = str(state.get("error") or state.get("message") or "").strip()
                return f"执行失败：{reason}" if reason else "执行失败"
            return "未注入"
        status = str(state.get("status") or "").strip()
        if status == "injecting":
            return "正在注入"
        if status == "success":
            return str(state.get("message") or "注入成功")
        if status == "failed":
            reason = str(state.get("error") or state.get("message") or "").strip()
            return f"注入失败：{reason}" if reason else "注入失败"
        return "未注入"

    def set_auto_enabled(self, script_id: str, enabled: bool) -> None:
        """把自动注入开关变化交给主窗口保存和调度。"""
        if self.on_auto_changed is not None:
            self.on_auto_changed(str(script_id or ""), bool(enabled))

    def set_runtime_toggle_enabled(self, script_id: str, enabled: str) -> None:
        """把长期脚本开关变化交给主窗口保存。"""
        if self.on_runtime_toggle_changed is not None:
            self.on_runtime_toggle_changed(str(script_id or ""), str(enabled or ""))

    def inject_script(self, script: dict) -> None:
        """请求 DevTools worker 对当前小程序手工注入脚本。"""
        if self.devtools_service is None or not hasattr(self.devtools_service, "inject_js_script"):
            return
        self.devtools_service.inject_js_script(self.record, dict(script), automatic=False)

    def enable_runtime_script(self, script: dict) -> None:
        """请求 DevTools worker 启用当前详情卡片的长期脚本。"""
        if self.devtools_service is None or not hasattr(self.devtools_service, "enable_runtime_js_script"):
            return
        self.devtools_service.enable_runtime_js_script(self.record, dict(script))

    def disable_runtime_script(self, script: dict) -> None:
        """请求 DevTools worker 取消当前详情卡片的长期脚本。"""
        if self.devtools_service is None or not hasattr(self.devtools_service, "disable_runtime_js_script"):
            return
        self.devtools_service.disable_runtime_js_script(self.record, dict(script))

    def remove_script(self, script: dict) -> None:
        """请求主窗口删除导入脚本。"""
        if self.on_remove_requested is not None:
            self.on_remove_requested(dict(script))

    def import_js_file(self) -> None:
        """打开文件选择器并把选中路径交给主窗口异步处理。"""
        file_path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "导入 JS 文件",
            "",
            "JavaScript (*.js)",
        )
        if file_path and self.on_import_requested is not None:
            self.on_import_requested(file_path)

    def refresh_catalog(self) -> None:
        """请求目录服务重新扫描 JS 文件。"""
        if self.catalog_service is not None and hasattr(self.catalog_service, "refresh"):
            self.catalog_service.refresh()


class JsInjectionDialog(ChromeDialog):
    """主窗口 JS 文件注入配置弹窗。"""

    def __init__(
        self,
        catalog_service=None,
        devtools_service=None,
        *,
        auto_enabled_getter: Callable[[], dict[str, bool]] | None = None,
        runtime_toggle_enabled_getter: Callable[[], dict[str, str]] | None = None,
        on_auto_changed: Callable[[str, bool], None] | None = None,
        on_runtime_toggle_changed: Callable[[str, str], None] | None = None,
        on_import_requested: Callable[[str], None] | None = None,
        on_remove_requested: Callable[[dict], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """初始化主窗口 JS 注入弹窗。"""
        super().__init__(parent)
        self.setWindowTitle("JS文件注入")
        self.resize(760, 520)
        root = self.content_layout()
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)
        self.table_widget = JsInjectionTableWidget(
            catalog_service,
            devtools_service,
            manual_mode=False,
            auto_enabled_getter=auto_enabled_getter,
            runtime_toggle_enabled_getter=runtime_toggle_enabled_getter,
            on_auto_changed=on_auto_changed,
            on_runtime_toggle_changed=on_runtime_toggle_changed,
            on_import_requested=on_import_requested,
            on_remove_requested=on_remove_requested,
            parent=self,
        )
        root.addWidget(self.table_widget, 1)


class JsInjectionPage(QWidget):
    """小程序详情页中的 JS 手工注入页面。"""

    def __init__(
        self,
        record: dict,
        catalog_service=None,
        devtools_service=None,
        parent: QWidget | None = None,
    ) -> None:
        """初始化详情页手工注入列表。"""
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)
        self.table_widget = JsInjectionTableWidget(
            catalog_service,
            devtools_service,
            record=record,
            manual_mode=True,
            parent=self,
        )
        root.addWidget(self.table_widget, 1)

    def update_record(self, record: dict) -> None:
        """详情页记录刷新时同步内部列表上下文。"""
        self.table_widget.update_record(record)
