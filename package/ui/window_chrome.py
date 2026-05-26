"""提供项目自绘无边框窗口标题栏和窗口基类。"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
)


class ChromeTitleBar(QWidget):
    """统一窗口标题栏，负责标题展示和窗口控制按钮。"""

    minimize_requested = Signal()
    maximize_requested = Signal()
    close_requested = Signal()

    def __init__(
        self,
        title: str = "",
        subtitle: str = "",
        *,
        show_minimize: bool = True,
        show_maximize: bool = True,
        show_close: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        """初始化标题栏文本和控制按钮。"""
        super().__init__(parent)
        self.setObjectName("ChromeTitleBar")
        self.setFixedHeight(44)
        root = QHBoxLayout(self)
        root.setContentsMargins(14, 0, 8, 0)
        root.setSpacing(8)

        title_box = QHBoxLayout()
        title_box.setContentsMargins(0, 0, 0, 0)
        title_box.setSpacing(8)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("ChromeTitle")
        self.title_label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        title_box.addWidget(self.title_label)
        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setObjectName("ChromeSubtitle")
        self.subtitle_label.setVisible(bool(str(subtitle).strip()))
        title_box.addWidget(self.subtitle_label)
        title_box.addStretch(1)
        root.addLayout(title_box, 1)
        root.addItem(QSpacerItem(8, 8, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))

        self.minimize_button = self._build_control_button("ChromeMinimizeButton", "-", "最小化")
        self.minimize_button.setVisible(show_minimize)
        self.minimize_button.clicked.connect(self.minimize_requested.emit)
        root.addWidget(self.minimize_button)

        self.maximize_button = self._build_control_button("ChromeMaximizeButton", "□", "最大化/还原")
        self.maximize_button.setVisible(show_maximize)
        self.maximize_button.clicked.connect(self.maximize_requested.emit)
        root.addWidget(self.maximize_button)

        self.close_button = self._build_control_button("ChromeCloseButton", "×", "关闭")
        self.close_button.setVisible(show_close)
        self.close_button.clicked.connect(self.close_requested.emit)
        root.addWidget(self.close_button)

    def _build_control_button(self, object_name: str, text: str, tooltip: str) -> QPushButton:
        """创建统一尺寸的标题栏控制按钮。"""
        button = QPushButton(text, self)
        button.setObjectName(object_name)
        button.setProperty("chromeControl", "true")
        button.setToolTip(tooltip)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFixedSize(34, 30)
        return button

    def set_title(self, title: str) -> None:
        """更新标题文本。"""
        self.title_label.setText(str(title or ""))

    def set_subtitle(self, subtitle: str) -> None:
        """更新副标题文本并根据内容切换可见性。"""
        text = str(subtitle or "").strip()
        self.subtitle_label.setText(text)
        self.subtitle_label.setVisible(bool(text))

    def title_text(self) -> str:
        """返回当前标题文本，便于测试和状态同步。"""
        return self.title_label.text()


class ChromeWindowMixin:
    """为无边框窗口提供标题同步、拖拽和基础控制行为。"""

    title_bar: ChromeTitleBar

    def _init_chrome_behavior(self) -> None:
        """安装无边框标志和标题栏事件过滤器。"""
        self._chrome_drag_offset: QPoint | None = None
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.FramelessWindowHint)
        self.title_bar.installEventFilter(self)

    def setWindowTitle(self, title: str) -> None:
        """同步 Qt 窗口标题到自绘标题栏。"""
        super().setWindowTitle(title)
        if hasattr(self, "title_bar"):
            self.title_bar.set_title(title)

    def eventFilter(self, watched, event) -> bool:
        """处理标题栏拖拽和双击最大化。"""
        if watched is getattr(self, "title_bar", None):
            if event.type() == QEvent.Type.MouseButtonDblClick and event.button() == Qt.MouseButton.LeftButton:
                if hasattr(self, "toggle_maximized"):
                    self.toggle_maximized()
                    return True
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._chrome_drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                return True
            if event.type() == QEvent.Type.MouseMove and self._chrome_drag_offset is not None:
                if event.buttons() & Qt.MouseButton.LeftButton and not self.isMaximized():
                    self.move(event.globalPosition().toPoint() - self._chrome_drag_offset)
                    return True
            if event.type() == QEvent.Type.MouseButtonRelease:
                self._chrome_drag_offset = None
        return super().eventFilter(watched, event)


class ChromeMainWindow(ChromeWindowMixin, QMainWindow):
    """带统一自绘标题栏的主窗口基类。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        """初始化主窗口外壳和内容承载区。"""
        super().__init__(parent)
        self._chrome_content_widget: QWidget | None = None
        self._chrome_shell = QWidget(self)
        self._chrome_shell.setObjectName("ChromeShell")
        shell_layout = QVBoxLayout(self._chrome_shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)

        self.title_bar = ChromeTitleBar(show_minimize=True, show_maximize=True, show_close=True, parent=self._chrome_shell)
        self.title_bar.minimize_requested.connect(self.showMinimized)
        self.title_bar.maximize_requested.connect(self.toggle_maximized)
        self.title_bar.close_requested.connect(self.close)
        shell_layout.addWidget(self.title_bar)

        self._chrome_content_host = QWidget(self._chrome_shell)
        self._chrome_content_host.setObjectName("ChromeContent")
        self._chrome_content_layout = QVBoxLayout(self._chrome_content_host)
        self._chrome_content_layout.setContentsMargins(0, 0, 0, 0)
        self._chrome_content_layout.setSpacing(0)
        shell_layout.addWidget(self._chrome_content_host, 1)

        super().setCentralWidget(self._chrome_shell)
        self._init_chrome_behavior()

    def setCentralWidget(self, widget: QWidget | None) -> None:
        """把业务中心控件挂载到自绘窗口内容区。"""
        if widget is None:
            return
        if self._chrome_content_widget is not None:
            self._chrome_content_layout.removeWidget(self._chrome_content_widget)
            self._chrome_content_widget.setParent(None)
        self._chrome_content_widget = widget
        self._chrome_content_layout.addWidget(widget)

    def content_widget(self) -> QWidget | None:
        """返回当前业务中心控件。"""
        return self._chrome_content_widget

    def toggle_maximized(self) -> None:
        """在最大化和普通窗口状态之间切换。"""
        if self.isMaximized():
            self.showNormal()
            self.title_bar.maximize_button.setText("□")
        else:
            self.showMaximized()
            self.title_bar.maximize_button.setText("❐")


class ChromeDialog(ChromeWindowMixin, QDialog):
    """带统一自绘标题栏的弹窗基类。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        """初始化弹窗外壳和内容布局。"""
        super().__init__(parent)
        self._chrome_shell_layout = QVBoxLayout(self)
        self._chrome_shell_layout.setContentsMargins(0, 0, 0, 0)
        self._chrome_shell_layout.setSpacing(0)

        self.title_bar = ChromeTitleBar(show_minimize=False, show_maximize=False, show_close=True, parent=self)
        self.title_bar.close_requested.connect(self.reject)
        self._chrome_shell_layout.addWidget(self.title_bar)

        self._chrome_content_host = QWidget(self)
        self._chrome_content_host.setObjectName("ChromeContent")
        self._chrome_content_layout = QVBoxLayout(self._chrome_content_host)
        self._chrome_content_layout.setContentsMargins(0, 0, 0, 0)
        self._chrome_content_layout.setSpacing(0)
        self._chrome_shell_layout.addWidget(self._chrome_content_host, 1)

        self._init_chrome_behavior()

    def content_layout(self) -> QVBoxLayout:
        """返回业务内容布局，弹窗控件应添加到这里。"""
        return self._chrome_content_layout
