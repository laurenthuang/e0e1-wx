"""实现主界面模块按钮控件，并兼容导出小程序卡片。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton, QSizePolicy, QWidget

from package.ui.cards.card_widget import MiniProgramCard


class ModuleButton(QPushButton):
    def __init__(self, title: str, action_only: bool = False, parent: QWidget | None = None) -> None:
        """初始化模块按钮，并区分状态按钮和动作按钮。"""
        super().__init__(parent)
        self.title = title
        self.action_only = action_only
        self.setCheckable(not action_only)
        self.setProperty("moduleButton", True)
        self.setProperty("actionButton", "true" if action_only else "false")
        self.setProperty("variant", "secondary")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(58)
        self.setMaximumHeight(58)
        if not action_only:
            self.toggled.connect(self.refresh_text)
        self.refresh_text(False)

    def refresh_text(self, checked: bool) -> None:
        """根据按钮状态刷新显示文本。"""
        if self.action_only:
            self.setText(self.title)
            return
        state_text = "开启" if checked else "关闭"
        self.setText(f"{self.title} · {state_text}")

__all__ = ["MiniProgramCard", "ModuleButton"]
