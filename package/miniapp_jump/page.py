"""实现小程序详情页中的跨小程序跳转页面。"""

from __future__ import annotations

import queue

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QScrollArea,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
)

from package.applet_detail.reconnect_hint import (
    devtools_session_started,
    show_miniapp_reconnect_hint,
)
from package.decompiler import DecompileTaskRunner
from package.miniapp_jump.record_context import jump_identifier_payload
from package.miniapp_jump.state import default_miniapp_jump_state


class MiniAppJumpPage(QWidget):
    """展示跨小程序跳转状态，并把跳转命令转发给共享服务。"""

    STATUS_STRIP_HEIGHT_RATIO = 0.25
    RECONNECT_FAILURE_MARKERS = ("等待小程序回连", "小程序未回连", "No miniapp client connected", "miniapp disconnected")
    DEFAULT_HELP_MESSAGE = "通过当前已回连的小程序上下文弹出微信确认框，确认后跳转到指定 AppID，不接管小程序其他功能。"
    STATUS_TEXT = {
        "stopped": "未执行",
        "executing": "跳转中",
        "success": "跳转成功",
        "failed": "跳转失败",
        "cancelled": "任务已取消",
    }

    def __init__(self, record: dict, devtools_service=None, parent: QWidget | None = None) -> None:
        """初始化跨小程序跳转页面。"""
        super().__init__(parent)
        self.record = dict(record)
        self.devtools_service = devtools_service
        self._last_reconnect_failure_signature: tuple[str, str] | None = None
        self.identifier_runner: DecompileTaskRunner | None = None
        self.identifier_task_id: int | None = None
        self.identifier_cache_key: tuple | None = None
        self.identifier_loaded_key: tuple | None = None
        self.identifier_appids: list[str] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        self.info_frame = QFrame()
        self.info_frame.setObjectName("StatusStrip")
        self.info_frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.info_layout = QVBoxLayout(self.info_frame)
        self.info_layout.setContentsMargins(10, 8, 10, 8)
        self.info_layout.setSpacing(6)
        self.info_grid = QGridLayout()
        self.info_grid.setContentsMargins(0, 0, 0, 0)
        self.info_grid.setHorizontalSpacing(8)
        self.info_grid.setVerticalSpacing(2)
        self.status_value = self.add_row(self.info_grid, 0, "当前状态")
        self.target_value = self.add_row(self.info_grid, 1, "目标 AppID")
        self.path_value = self.add_row(self.info_grid, 2, "目标 Path")
        self.owner_value = self.add_row(self.info_grid, 3, "当前归属")
        self.action_value = self.add_row(self.info_grid, 4, "最近操作")
        self.message_value = self.add_row(self.info_grid, 5, "最近消息")
        self.error_value = self.add_row(self.info_grid, 6, "错误信息")
        self.info_layout.addLayout(self.info_grid)
        self.info_layout.addStretch(1)
        root.addWidget(self.info_frame)

        action_row = QHBoxLayout()
        action_row.setSpacing(6)
        self.appid_input = QLineEdit()
        self.appid_input.setPlaceholderText("请输入目标小程序 AppID，例如 wx1234567890abcdef")
        action_row.addWidget(self.appid_input, 1)
        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText("可选：请输入目标页面路径，例如 pages/index/index?foo=bar")
        action_row.addWidget(self.path_input, 1)
        self.start_button = QPushButton("立即跳转")
        self.start_button.setProperty("variant", "primary")
        self.start_button.setProperty("size", "sm")
        self.start_button.clicked.connect(self.start_jump)
        action_row.addWidget(self.start_button)
        self.cancel_button = QPushButton("取消当前任务")
        self.cancel_button.setProperty("variant", "danger")
        self.cancel_button.setProperty("size", "sm")
        self.cancel_button.clicked.connect(self.cancel_jump)
        action_row.addWidget(self.cancel_button)
        action_row.addItem(QSpacerItem(10, 10, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))
        root.addLayout(action_row)
        self.identifier_panel = self.build_identifier_panel()
        root.addWidget(self.identifier_panel, 1)

        if self.devtools_service is not None and hasattr(self.devtools_service, "miniapp_jump_state_changed"):
            self.devtools_service.miniapp_jump_state_changed.connect(self.handle_jump_state_changed)

        self.identifier_timer = QTimer(self)
        self.identifier_timer.timeout.connect(self.process_identifier_events)

        self.refresh_state()
        self.refresh_jump_identifiers()

    def add_row(self, grid: QGridLayout, row: int, name: str) -> QLabel:
        """向状态信息区添加标题和值标签。"""
        title = QLabel(name)
        title.setObjectName("MutedLabel")
        value = QLabel("-")
        value.setWordWrap(True)
        value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        grid.addWidget(title, row, 0)
        grid.addWidget(value, row, 1)
        grid.setColumnStretch(1, 1)
        return value

    def build_identifier_panel(self) -> QFrame:
        """构建从正则匹配结果生成的跨小程序跳转候选卡片区。"""
        frame = QFrame()
        frame.setObjectName("SectionCard")
        frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("正则匹配微信标识")
        title.setObjectName("SectionTitle")
        header.addWidget(title)
        self.identifier_status_label = QLabel("-")
        self.identifier_status_label.setObjectName("MutedLabel")
        header.addWidget(self.identifier_status_label, 1)
        self.identifier_refresh_button = QPushButton("刷新")
        self.identifier_refresh_button.setProperty("variant", "ghost")
        self.identifier_refresh_button.setProperty("size", "sm")
        self.identifier_refresh_button.clicked.connect(lambda _checked=False: self.refresh_jump_identifiers(force=True))
        header.addWidget(self.identifier_refresh_button)
        layout.addLayout(header)

        self.identifier_rows_scroll_area = QScrollArea()
        self.identifier_rows_scroll_area.setWidgetResizable(True)
        self.identifier_rows_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.identifier_rows_scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.identifier_rows_scroll_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.identifier_rows_widget = QWidget()
        self.identifier_rows_layout = QVBoxLayout(self.identifier_rows_widget)
        self.identifier_rows_layout.setContentsMargins(0, 0, 0, 0)
        self.identifier_rows_layout.setSpacing(6)
        self.identifier_rows_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.identifier_rows_scroll_area.setWidget(self.identifier_rows_widget)
        layout.addWidget(self.identifier_rows_scroll_area, 1)
        return frame

    def current_state(self) -> dict:
        """返回当前卡片的跨小程序跳转状态快照。"""
        if self.devtools_service is not None and hasattr(self.devtools_service, "miniapp_jump_state_for_record"):
            return self.devtools_service.miniapp_jump_state_for_record(self.record)
        return default_miniapp_jump_state(
            record_id=int(self.record.get("id") or 0),
            owner_key=str(self.record.get("wxid") or ""),
            display_name=str(self.record.get("name") or ""),
        )

    def refresh_state(self) -> None:
        """把当前状态快照渲染到页面控件。"""
        state = self.current_state()
        status = str(state.get("status") or "stopped")
        busy = status == "executing"
        status_text = self.STATUS_TEXT.get(status, status)
        target_text = str(state.get("target_appid") or "-")
        path_text = str(state.get("target_path") or "-")
        owner_text = str(state.get("display_name") or "-")
        action_text = str(state.get("last_action") or "-")
        error_text = str(state.get("error") or "-")
        raw_message = str(state.get("message") or "").strip()
        message_text = self.DEFAULT_HELP_MESSAGE if raw_message in {"", "未执行"} else raw_message
        self.status_value.setText(status_text)
        self.target_value.setText(target_text)
        self.path_value.setText(path_text)
        self.owner_value.setText(owner_text)
        self.action_value.setText(action_text)
        self.message_value.setText(message_text)
        self.error_value.setText(error_text)
        enabled = self.devtools_service is not None
        self.start_button.setEnabled(enabled and not busy)
        self.cancel_button.setEnabled(enabled and busy)
        self.sync_status_strip_height()

    @classmethod
    def compute_status_strip_height(cls, page_height: int, content_height: int) -> int:
        """根据页面高度与内容高度计算状态栏应使用的目标高度。"""
        safe_page_height = max(int(page_height or 0), 0)
        safe_content_height = max(int(content_height or 0), 0)
        return max(safe_content_height, int(safe_page_height * cls.STATUS_STRIP_HEIGHT_RATIO))

    def sync_status_strip_height(self) -> None:
        """把状态栏高度同步为页面高度的约四分之一，同时保证足够容纳当前内容。"""
        target_height = self.compute_status_strip_height(self.height(), self.info_frame.sizeHint().height())
        self.info_frame.setFixedHeight(target_height)

    def resizeEvent(self, event) -> None:
        """窗口尺寸变化时同步更新状态栏高度。"""
        super().resizeEvent(event)
        self.sync_status_strip_height()

    def showEvent(self, event) -> None:
        """页面首次显示时同步状态栏高度，避免初始布局偏差。"""
        super().showEvent(event)
        self.sync_status_strip_height()

    def start_jump(self) -> None:
        """读取目标 AppID 和可选 Path 并转发跨小程序跳转命令。"""
        appid = self.appid_input.text().strip()
        path = self.path_input.text().strip()
        self.request_jump(appid, path)

    def request_jump(self, appid: str, path: str = "") -> None:
        """校验目标并转发跨小程序跳转命令。"""
        appid = str(appid or "").strip()
        path = str(path or "").strip()
        if not appid:
            self.message_value.setText("目标 AppID 不能为空。")
            return
        self.ensure_devtools_session_started()
        if self.needs_miniapp_reconnect_hint():
            self.show_reconnect_hint()
            return
        if self.devtools_service is not None and hasattr(self.devtools_service, "jump_to_mini_program"):
            self.devtools_service.jump_to_mini_program(self.record, appid, path)

    def jump_to_identifier(self, appid: str) -> None:
        """点击候选 AppID 卡片时直接发起跳转。"""
        target = str(appid or "").strip()
        self.appid_input.setText(target)
        self.path_input.clear()
        self.request_jump(target, "")

    def cancel_jump(self) -> None:
        """请求后台取消当前记录的跨小程序跳转任务。"""
        if self.devtools_service is not None and hasattr(self.devtools_service, "cancel_miniapp_jump"):
            self.devtools_service.cancel_miniapp_jump(self.record)

    def handle_jump_state_changed(self, record_id: int, _state: dict) -> None:
        """仅在事件属于当前记录时刷新页面。"""
        if int(record_id or 0) != int(self.record.get("id") or 0):
            return
        self.refresh_state()
        self.maybe_show_reconnect_failure_hint(_state)

    def update_record(self, record: dict) -> None:
        """切换记录时取消旧任务并刷新页面。"""
        previous_record = dict(self.record)
        self.record = dict(record)
        if int(previous_record.get("id") or 0) != int(self.record.get("id") or 0):
            self.cancel_record(previous_record)
        self.refresh_state()
        self.refresh_jump_identifiers()

    def cancel_record(self, record: dict) -> None:
        """取消指定记录的跨小程序跳转任务。"""
        if self.devtools_service is not None and hasattr(self.devtools_service, "cancel_miniapp_jump"):
            self.devtools_service.cancel_miniapp_jump(record)

    def current_devtools_state(self) -> dict:
        """返回当前卡片对应的共享调试会话状态。"""
        if self.devtools_service is not None and hasattr(self.devtools_service, "state_for_record"):
            state = self.devtools_service.state_for_record(self.record)
            if isinstance(state, dict):
                return dict(state)
        return {}

    def should_start_devtools_session(self) -> bool:
        """判断当前卡片在发起跳转前是否需要先启动或切换 DevTools 会话。"""
        state = self.current_devtools_state()
        if not isinstance(state, dict):
            return True
        if not bool(state.get("worker_alive")):
            return True
        if not bool(state.get("current_record")):
            return True
        if str(state.get("status") or "") == "starting":
            return False
        return not devtools_session_started(state)

    def ensure_devtools_session_started(self) -> None:
        """在提示用户回连前，优先为当前卡片拉起对应的 DevTools 会话。"""
        if not self.should_start_devtools_session():
            return
        self.message_value.setText("正在启动当前小程序的 DevTools 会话，请等待小程序回连后再跳转。")
        if self.devtools_service is not None and hasattr(self.devtools_service, "start_debug"):
            self.devtools_service.start_debug(self.record)

    def needs_miniapp_reconnect_hint(self) -> bool:
        """在发起跳转前判断当前卡片是否已具备可直接跳转的小程序回连会话。"""
        state = self.current_devtools_state()
        if not isinstance(state, dict):
            return True
        if not bool(state.get("worker_alive")):
            return True
        if not bool(state.get("current_record")):
            return True
        if not devtools_session_started(state):
            return True
        return not bool(state.get("miniapp"))

    def maybe_show_reconnect_failure_hint(self, state: dict) -> None:
        """当异步跳转失败且原因是未回连时，仅弹一次回连提示。"""
        if not self.is_reconnect_failure_state(state):
            self._last_reconnect_failure_signature = None
            return
        signature = (str(state.get("message") or ""), str(state.get("error") or ""))
        if signature == self._last_reconnect_failure_signature:
            return
        self._last_reconnect_failure_signature = signature
        self.show_reconnect_hint()

    @classmethod
    def is_reconnect_failure_state(cls, state: dict) -> bool:
        """判断当前跳转失败是否由小程序未回连导致。"""
        if not isinstance(state, dict) or str(state.get("status") or "") != "failed":
            return False
        combined = f"{state.get('message') or ''}\n{state.get('error') or ''}"
        return any(marker in combined for marker in cls.RECONNECT_FAILURE_MARKERS)

    def show_reconnect_hint(self) -> None:
        """显示“小程序未回连”的统一提示。"""
        show_miniapp_reconnect_hint(self)

    def shutdown_worker(self) -> None:
        """详情页关闭时取消当前记录仍在执行中的跳转任务。"""
        self.cancel_record(self.record)
        if self.identifier_task_id is not None and self.identifier_runner is not None:
            self.identifier_runner.cancel(self.identifier_task_id)
            self.identifier_task_id = None
        if hasattr(self, "identifier_timer"):
            self.identifier_timer.stop()
        if self.identifier_runner is not None:
            self.identifier_runner.shutdown(wait=False)
            self.identifier_runner = None

    def identifier_payload_key(self, payload: dict) -> tuple:
        """生成候选 AppID 提取任务的轻量去重键。"""
        fallback = payload.get("fallback_results") if isinstance(payload.get("fallback_results"), list) else []
        fallback_texts = tuple(str(item.get("match_text") or "") for item in fallback[:20] if isinstance(item, dict))
        return (
            str(payload.get("cache_path") or ""),
            str(payload.get("applet_id") or ""),
            tuple(str(item) for item in payload.get("new_folders", []) if str(item).strip()),
            tuple(str(item) for item in payload.get("output_dirs", []) if str(item).strip()),
            fallback_texts,
        )

    def ensure_identifier_runner(self) -> DecompileTaskRunner:
        """按需启动候选 AppID 提取后台进程。"""
        if self.identifier_runner is None:
            self.identifier_runner = DecompileTaskRunner()
        return self.identifier_runner

    def refresh_jump_identifiers(self, force: bool = False) -> None:
        """提交后台任务，从正则匹配结果中提取跳转候选 AppID。"""
        payload = jump_identifier_payload(self.record)
        key = self.identifier_payload_key(payload)
        if not force and key == self.identifier_loaded_key:
            return
        if not force and key == self.identifier_cache_key and self.identifier_task_id is not None:
            return
        if self.identifier_task_id is not None and self.identifier_runner is not None:
            self.identifier_runner.cancel(self.identifier_task_id)
        self.identifier_cache_key = key
        self.identifier_loaded_key = None
        self.identifier_appids = []
        self.render_identifier_rows([])
        self.identifier_status_label.setText("正在提取...")
        self.identifier_task_id = self.ensure_identifier_runner().submit("extract_jump_identifiers", payload)
        self.identifier_timer.start(100)

    def process_identifier_events(self) -> None:
        """从后台进程非阻塞读取候选 AppID 提取结果。"""
        if self.identifier_runner is None:
            return
        for _index in range(30):
            try:
                event = self.identifier_runner.get_event_nowait()
            except queue.Empty:
                break
            task_id = int(event.get("task_id") or 0)
            if self.identifier_task_id is not None and task_id != self.identifier_task_id:
                continue
            event_type = str(event.get("type") or "")
            if event_type == "jump_identifiers_loaded":
                self.identifier_task_id = None
                self.identifier_loaded_key = self.identifier_cache_key
                self.identifier_appids = [str(item) for item in event.get("appids", []) if str(item).strip()]
                self.identifier_status_label.setText(f"发现 {len(self.identifier_appids)} 个")
                self.render_identifier_rows(self.identifier_appids)
                self.identifier_timer.stop()
            elif event_type in {"extract_jump_identifiers_error", "extract_jump_identifiers_cancelled"}:
                self.identifier_task_id = None
                self.identifier_status_label.setText(str(event.get("message") or "提取失败"))
                self.render_identifier_rows([])
                self.identifier_timer.stop()

    def clear_identifier_rows(self) -> None:
        """清空当前候选 AppID 行。"""
        while self.identifier_rows_layout.count():
            item = self.identifier_rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def render_identifier_rows(self, appids: list[str]) -> None:
        """把去重后的 AppID 渲染为一行行可跳转卡片。"""
        self.clear_identifier_rows()
        if not appids:
            empty = QLabel("暂无可用微信标识，请先在反编译页完成正则匹配。")
            empty.setObjectName("MutedLabel")
            empty.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self.identifier_rows_layout.addWidget(empty)
            return
        for appid in appids:
            row = QFrame()
            row.setObjectName("StatusStrip")
            row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(10, 6, 10, 6)
            row_layout.setSpacing(8)
            name = QLabel(appid)
            name.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            row_layout.addWidget(name, 1)
            button = QPushButton("跳转")
            button.setProperty("variant", "primary")
            button.setProperty("size", "sm")
            button.clicked.connect(lambda _checked=False, target=appid: self.jump_to_identifier(target))
            row_layout.addWidget(button)
            self.identifier_rows_layout.addWidget(row)
