"""实现支持增量更新的小程序卡片控件。"""

from __future__ import annotations

import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMenu, QSizePolicy, QSpacerItem, QVBoxLayout, QWidget

from package.ui.cards.presenter import build_card_view_model
from package.ui.constants import CARD_HEIGHT


class StatusDot(QLabel):
    """显示小程序在线状态的圆点。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        """初始化圆点样式状态。"""
        super().__init__(parent)
        self.setObjectName("StatusDot")
        self.setFixedSize(12, 12)
        self.setProperty("active", "false")

    def set_active(self, active: bool) -> None:
        """按在线状态刷新样式。"""
        self.setProperty("active", "true" if active else "false")
        self.style().unpolish(self)
        self.style().polish(self)


class MiniProgramCard(QFrame):
    """支持 update_record 的小程序卡片。"""

    delete_requested = Signal(int)
    rebind_requested = Signal(int)
    detail_requested = Signal(dict)

    def __init__(self, record: dict, parent: QWidget | None = None) -> None:
        """根据数据库记录创建可增量刷新的小程序卡片。"""
        super().__init__(parent)
        self.record = dict(record)
        self.busy = False
        self.setObjectName("Card")
        self.setFixedHeight(CARD_HEIGHT)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.open_context_menu)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(8)

        self.dot = StatusDot()
        header.addWidget(self.dot, 0, Qt.AlignmentFlag.AlignTop)

        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        self.name_full_text = ""
        self.wxid_full_text = ""

        self.name_label = QLabel()
        self.name_label.setObjectName("CardTitle")
        self.name_label.setMinimumWidth(0)
        self.name_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        title_box.addWidget(self.name_label)

        self.wxid_label = QLabel()
        self.wxid_label.setObjectName("MutedLabel")
        self.wxid_label.setMinimumWidth(0)
        self.wxid_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.wxid_label.setWordWrap(False)
        title_box.addWidget(self.wxid_label)

        header.addLayout(title_box, 1)
        root.addLayout(header)
        root.addStretch(1)

        footer = QHBoxLayout()
        footer.setSpacing(6)

        self.status_label = QLabel()
        self.status_label.setObjectName("StatusBadge")
        footer.addWidget(self.status_label)

        footer.addItem(QSpacerItem(10, 10, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))

        self.time_label = QLabel()
        self.time_label.setObjectName("MutedLabel")
        footer.addWidget(self.time_label)

        root.addLayout(footer)
        self.update_record(record)

    def update_record(self, record: dict) -> None:
        """用最新监控记录增量刷新卡片文本与状态。"""
        self.record = dict(record)
        view_model = build_card_view_model(self.record)
        self.name_full_text = view_model.name_text
        self.wxid_full_text = view_model.wxid_text
        self.name_label.setToolTip(self.name_full_text)
        self.wxid_label.setToolTip(self.wxid_full_text)
        self.setProperty("active", "true" if view_model.active else "false")
        self.style().unpolish(self)
        self.style().polish(self)
        self.dot.set_active(view_model.active)
        self.status_label.setText("存活" if view_model.active else "已关闭")
        self.status_label.setProperty("status", "success" if view_model.active else "neutral")
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
        timestamp = float(self.record.get("last_seen") or self.record.get("start_time") or 0.0)
        self.time_label.setText(f"时间: {time.strftime('%H:%M:%S', time.localtime(timestamp)) if timestamp else '-'}")
        self.refresh_text_layout()

    def set_busy(self, busy: bool, message: str = "") -> None:
        """设置卡片繁忙态，例如删除中。"""
        self.busy = bool(busy)
        if message:
            self.status_label.setText(message)

    def resizeEvent(self, event) -> None:
        """尺寸变化时刷新省略文本。"""
        super().resizeEvent(event)
        self.refresh_text_layout()

    def mousePressEvent(self, event) -> None:
        """左键打开详情页。"""
        if event.button() == Qt.MouseButton.LeftButton and not self.busy:
            self.detail_requested.emit(dict(self.record))
        super().mousePressEvent(event)

    def set_equal_width(self, width: int) -> None:
        """按网格宽度统一设置卡片宽度。"""
        self.setFixedWidth(max(1, width))
        self.refresh_text_layout()

    def refresh_text_layout(self) -> None:
        """按当前控件宽度刷新文本省略号。"""
        name_width = max(40, self.name_label.width())
        name_metrics = QFontMetrics(self.name_label.font())
        self.name_label.setText(name_metrics.elidedText(self.name_full_text, Qt.TextElideMode.ElideRight, name_width))
        wxid_width = max(40, self.wxid_label.width())
        wxid_metrics = QFontMetrics(self.wxid_label.font())
        self.wxid_label.setText(wxid_metrics.elidedText(self.wxid_full_text, Qt.TextElideMode.ElideRight, wxid_width))

    def open_context_menu(self, position) -> None:
        """打开右键菜单并分发删除和重绑定动作。"""
        if self.busy:
            return
        record_id = int(self.record.get("id") or 0)
        if record_id <= 0:
            return
        menu = QMenu(self)
        actions = {label: menu.addAction(label) for label in self.context_action_labels()}
        selected_action = menu.exec(self.mapToGlobal(position))
        if selected_action == actions.get("删除记录"):
            self.delete_requested.emit(record_id)

    def context_action_labels(self) -> list[str]:
        """返回当前卡片右键菜单应展示的动作文本。"""
        return ["删除记录"]
