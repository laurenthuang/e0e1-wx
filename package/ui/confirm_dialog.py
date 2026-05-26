"""提供统一自绘风格的确认弹窗。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSpacerItem, QSizePolicy, QVBoxLayout, QWidget

from package.ui.window_chrome import ChromeDialog


class ChromeConfirmDialog(ChromeDialog):
    """统一确认弹窗，复用项目自绘标题栏和按钮样式。"""

    def __init__(
        self,
        *,
        title: str,
        message: str,
        confirm_text: str = "确定",
        cancel_text: str = "取消",
        confirm_variant: str = "primary",
        parent: QWidget | None = None,
    ) -> None:
        """初始化确认弹窗内容和操作按钮。"""
        super().__init__(parent)
        self.setWindowTitle(str(title or "确认操作"))
        self.setModal(True)
        self.resize(420, 180)

        root = self.content_layout()
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        body = QFrame(self)
        body.setObjectName("SectionCard")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(16, 14, 16, 14)
        body_layout.setSpacing(8)

        self.message_label = QLabel(str(message or "确认继续执行该操作？"))
        self.message_label.setWordWrap(True)
        self.message_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        body_layout.addWidget(self.message_label)
        root.addWidget(body, 1)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        button_row.addItem(QSpacerItem(10, 10, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))

        self.cancel_button = QPushButton(str(cancel_text or "取消"))
        self.cancel_button.setProperty("variant", "ghost")
        self.cancel_button.clicked.connect(self.reject)
        button_row.addWidget(self.cancel_button)

        self.confirm_button = QPushButton(str(confirm_text or "确定"))
        self.confirm_button.setProperty("variant", str(confirm_variant or "primary"))
        self.confirm_button.clicked.connect(self.accept)
        button_row.addWidget(self.confirm_button)

        root.addLayout(button_row)


def ask_danger_confirmation(
    parent: QWidget | None,
    *,
    title: str,
    message: str,
    confirm_text: str = "删除",
    cancel_text: str = "取消",
) -> bool:
    """显示危险操作确认弹窗，返回用户是否确认。"""
    dialog = ChromeConfirmDialog(
        parent=parent,
        title=title,
        message=message,
        confirm_text=confirm_text,
        cancel_text=cancel_text,
        confirm_variant="danger",
    )
    return dialog.exec() == ChromeConfirmDialog.DialogCode.Accepted
