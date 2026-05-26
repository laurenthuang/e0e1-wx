"""摘要：提供 MCP 后台启停、URL 展示和 CLI 添加命令弹窗。"""

from __future__ import annotations

from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
)

from package.mcp_control import McpControlService
from package.ui.window_chrome import ChromeDialog


class McpDialog(ChromeDialog):
    """主页面 MCP 入口弹窗，所有耗时操作交给 MCP 控制服务。"""

    def __init__(self, service: McpControlService, parent: QWidget | None = None) -> None:
        """初始化 MCP 控制弹窗、状态展示和 CLI 命令区域。"""
        super().__init__(parent)
        self.service = service
        self.setWindowTitle("MCP")
        self.setModal(True)

        root = self.content_layout()
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        self.status_label = QLabel("MCP 未启动")
        self.status_label.setObjectName("StatusBadge")
        self.status_label.setProperty("status", "neutral")
        root.addWidget(self.status_label)

        endpoint_label = QLabel("MCP 网址")
        root.addWidget(endpoint_label)
        endpoint_row = QHBoxLayout()
        endpoint_row.setSpacing(8)
        self.endpoint_input = QLineEdit()
        self.endpoint_input.setReadOnly(True)
        endpoint_row.addWidget(self.endpoint_input, 1)
        root.addLayout(endpoint_row)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.start_button = QPushButton("后台启动 MCP")
        self.start_button.setProperty("variant", "primary")
        self.start_button.clicked.connect(self.start_mcp)
        actions.addWidget(self.start_button)
        self.stop_button = QPushButton("停止 MCP")
        self.stop_button.setProperty("variant", "danger")
        self.stop_button.clicked.connect(self.stop_mcp)
        actions.addWidget(self.stop_button)
        actions.addItem(QSpacerItem(10, 10, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))
        root.addLayout(actions)

        commands_label = QLabel("CLI 添加/删除 MCP")
        root.addWidget(commands_label)
        self.commands_text = QPlainTextEdit()
        self.commands_text.setObjectName("CodePreview")
        self.commands_text.setReadOnly(True)
        self.commands_text.setMinimumHeight(96)
        root.addWidget(self.commands_text)

        log_frame = QFrame()
        log_frame.setObjectName("SectionCard")
        log_layout = QVBoxLayout(log_frame)
        log_layout.setContentsMargins(12, 12, 12, 12)
        log_layout.setSpacing(8)
        log_title = QLabel("运行日志")
        log_title.setObjectName("MutedLabel")
        log_layout.addWidget(log_title)
        self.log_text = QPlainTextEdit()
        self.log_text.setObjectName("CodePreview")
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumBlockCount(200)
        self.log_text.setMinimumHeight(110)
        log_layout.addWidget(self.log_text)
        root.addWidget(log_frame, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.service.state_changed.connect(self.apply_state)
        self.service.log_emitted.connect(self.append_log)
        self.apply_state(self.service.snapshot())
        self.service.request_status()
        self.setMinimumSize(780, 560)

    def start_mcp(self) -> None:
        """请求后台启动 MCP 服务。"""
        self.service.start_server()

    def stop_mcp(self) -> None:
        """请求后台停止 MCP 服务。"""
        self.service.stop_server()

    def apply_state(self, state: dict) -> None:
        """根据 MCP 服务状态刷新弹窗展示和按钮可用性。"""
        status = str(state.get("status") or "stopped")
        message = str(state.get("message") or "MCP 未启动")
        self.status_label.setText(message)
        self.status_label.setProperty("status", self.status_badge_kind(status))
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
        self.endpoint_input.setText(str(state.get("url") or ""))

        commands = state.get("commands") if isinstance(state.get("commands"), dict) else {}
        delete_commands = state.get("delete_commands") if isinstance(state.get("delete_commands"), dict) else {}
        self.commands_text.setPlainText(
            "\n".join(
                [
                    "添加 MCP:",
                    str(commands.get("claude") or ""),
                    str(commands.get("codex") or ""),
                    "",
                    "删除 MCP:",
                    str(delete_commands.get("claude") or ""),
                    str(delete_commands.get("codex") or ""),
                ]
            ).strip()
        )

        starting_or_running = status in {"starting", "running"}
        stopping = status == "stopping"
        self.start_button.setEnabled(not starting_or_running and not stopping)
        self.stop_button.setEnabled(starting_or_running and not stopping)
        if state.get("last_error"):
            self.append_log(str(state.get("last_error")))

    def append_log(self, message: str) -> None:
        """追加一行运行日志并滚动到底部。"""
        text = str(message or "").strip()
        if not text:
            return
        self.log_text.appendPlainText(text)
        self.log_text.moveCursor(QTextCursor.MoveOperation.End)

    @staticmethod
    def status_badge_kind(status: str) -> str:
        """把内部状态映射为已有 QSS 徽标颜色。"""
        if status == "running":
            return "success"
        if status == "starting" or status == "stopping":
            return "warning"
        if status == "failed":
            return "danger"
        return "neutral"
