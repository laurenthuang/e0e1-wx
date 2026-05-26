"""定义 Qt 应用全局样式表和现代安全分析工具视觉规范。"""

from __future__ import annotations

from textwrap import dedent


TOKENS = {
    "bg_app": "#F3F6FA",
    "bg_panel": "#FCFDFE",
    "bg_panel_soft": "#F7FAFC",
    "bg_panel_muted": "#F2F6F9",
    "button_bg": "#F2F5F8",
    "button_hover": "#EAF0F5",
    "button_pressed": "#E2E9F0",
    "button_disabled_bg": "#F7F9FB",
    "button_disabled_border": "#E4EAF0",
    "button_disabled_text": "#A0ACB8",
    "button_disabled_primary_bg": "#D8E0E7",
    "button_disabled_primary_text": "#7C8C9A",
    "button_disabled_danger_bg": "#F3E8E8",
    "button_disabled_danger_text": "#B49B9B",
    "border_soft": "#E3EAF1",
    "border_strong": "#D4DEE8",
    "border_accent": "#BAC9D7",
    "text_primary": "#1F2937",
    "text_secondary": "#5F6E82",
    "text_tertiary": "#7B8798",
    "accent": "#445C75",
    "accent_hover": "#3B5066",
    "accent_pressed": "#324555",
    "accent_soft": "#E4ECF4",
    "success_bg": "#EAF4EF",
    "success_fg": "#2F6A4F",
    "warning_bg": "#FDF2E3",
    "warning_fg": "#9A6223",
    "danger_bg": "#F6E5E5",
    "danger_fg": "#9C4B4B",
    "info_bg": "#EAF0F6",
    "info_fg": "#47637F",
    "neutral_bg": "#EEF2F5",
    "neutral_fg": "#617284",
    "focus_ring": "#C8D6E4",
    "selection_bg": "#E7EEF5",
    "selection_fg": "#1F2937",
    "scrollbar": "#D2DAE4",
    "scrollbar_hover": "#A7B5C4",
    "radius_sm": "8px",
    "radius_md": "12px",
    "radius_lg": "16px",
}

UI_FONT_STACK = '"HarmonyOS Sans SC", "PingFang SC", "Microsoft YaHei UI", "Segoe UI", sans-serif'
MODULE_BUTTON_FONT_STACK = '"Microsoft YaHei UI", "HarmonyOS Sans SC", "PingFang SC", "Segoe UI", sans-serif'
MONO_FONT_STACK = '"Cascadia Mono", "JetBrains Mono", "Consolas", monospace'


def section(rule: str) -> str:
    """返回格式化后的 QSS 片段。"""
    return dedent(rule).strip()


def build_foundation_qss() -> str:
    """基础背景、字体和文本样式。"""
    return section(
        f"""
        QWidget {{
            background-color: {TOKENS["bg_app"]};
            color: {TOKENS["text_secondary"]};
            font-family: {UI_FONT_STACK};
            font-size: 13px;
        }}

        QMainWindow, QDialog {{
            background-color: {TOKENS["bg_app"]};
        }}

        QLabel {{
            background-color: transparent;
            color: {TOKENS["text_secondary"]};
        }}

        QLabel#TitleLabel, QLabel#PageTitle {{
            font-size: 22px;
            color: {TOKENS["text_primary"]};
        }}

        QLabel#SectionTitle {{
            font-size: 15px;
            color: {TOKENS["text_primary"]};
        }}

        QLabel#DetailHeaderTitle {{
            font-size: 15px;
            font-weight: 600;
            color: {TOKENS["text_primary"]};
        }}

        QLabel#CardTitle {{
            font-size: 16px;
            font-weight: 550;
            color: {TOKENS["text_primary"]};
        }}

        QLabel#MutedLabel, QLabel#HintText {{
            color: {TOKENS["text_tertiary"]};
        }}

        QLabel#MonitorStatusPill {{
            background-color: {TOKENS["info_bg"]};
            border: 1px solid {TOKENS["border_soft"]};
            border-radius: 10px;
            color: {TOKENS["info_fg"]};
            padding: 3px 9px;
            font-size: 12px;
        }}

        QLabel#StatusBadge {{
            border-radius: 10px;
            padding: 3px 8px;
            font-size: 12px;
        }}

        QLabel#StatusBadge[status="info"] {{
            background-color: {TOKENS["info_bg"]};
            color: {TOKENS["info_fg"]};
        }}

        QLabel#StatusBadge[status="success"] {{
            background-color: {TOKENS["success_bg"]};
            color: {TOKENS["success_fg"]};
        }}

        QLabel#StatusBadge[status="warning"] {{
            background-color: {TOKENS["warning_bg"]};
            color: {TOKENS["warning_fg"]};
        }}

        QLabel#StatusBadge[status="danger"] {{
            background-color: {TOKENS["danger_bg"]};
            color: {TOKENS["danger_fg"]};
        }}

        QLabel#StatusBadge[status="neutral"] {{
            background-color: #E4EAF0;
            color: #5E6D7C;
        }}

        QLabel[status="ok"] {{
            background-color: {TOKENS["success_bg"]};
            color: {TOKENS["success_fg"]};
            padding: 3px 8px;
            border-radius: 10px;
        }}

        QLabel[status="warn"] {{
            background-color: {TOKENS["warning_bg"]};
            color: {TOKENS["warning_fg"]};
            padding: 3px 8px;
            border-radius: 10px;
        }}

        QLabel[status="error"] {{
            background-color: {TOKENS["danger_bg"]};
            color: {TOKENS["danger_fg"]};
            padding: 3px 8px;
            border-radius: 10px;
        }}

        QLabel#StatusDot {{
            min-width: 12px;
            min-height: 12px;
            max-width: 12px;
            max-height: 12px;
            border-radius: 6px;
            background-color: #C8D3DF;
        }}

        QLabel#StatusDot[active="true"] {{
            background-color: {TOKENS["accent"]};
        }}
        """
    )


def build_surface_qss() -> str:
    """页面层级和卡片表面样式。"""
    return section(
        f"""
        QFrame#Surface, QFrame#PageSurface {{
            background-color: {TOKENS["bg_panel_soft"]};
            border: 1px solid {TOKENS["border_soft"]};
            border-radius: {TOKENS["radius_lg"]};
        }}

        QFrame#Toolbar, QFrame#ToolbarSurface {{
            background-color: {TOKENS["bg_panel"]};
            border: 1px solid {TOKENS["border_soft"]};
            border-radius: {TOKENS["radius_lg"]};
        }}

        QFrame#Card, QFrame#SectionCard {{
            background-color: {TOKENS["bg_panel"]};
            border: 1px solid {TOKENS["border_soft"]};
            border-radius: {TOKENS["radius_md"]};
        }}

        QFrame#Card:hover, QFrame#SectionCard:hover {{
            background-color: {TOKENS["bg_panel_soft"]};
            border-color: {TOKENS["border_strong"]};
        }}

        QFrame#Card[active="true"], QFrame#SectionCard[active="true"] {{
            border-color: {TOKENS["accent"]};
            background-color: #F7FAFD;
        }}

        QFrame#Card[active="true"]:hover, QFrame#SectionCard[active="true"]:hover {{
            border-color: {TOKENS["accent_hover"]};
            background-color: #F2F7FB;
        }}

        QFrame#Card[active="false"], QFrame#SectionCard[active="false"] {{
            background-color: {TOKENS["bg_panel_soft"]};
            border-color: #E7ECF1;
        }}

        QFrame#Card[active="false"]:hover, QFrame#SectionCard[active="false"]:hover {{
            background-color: #F3F6F9;
            border-color: #DCE3EA;
        }}

        QFrame#Card[active="true"] QLabel#CardTitle,
        QFrame#SectionCard[active="true"] QLabel#CardTitle {{
            color: {TOKENS["text_primary"]};
            font-weight: 600;
        }}

        QFrame#Card[active="false"] QLabel#CardTitle,
        QFrame#SectionCard[active="false"] QLabel#CardTitle {{
            color: #4E5F72;
            font-weight: 600;
        }}

        QFrame#Card[active="false"] QLabel#MutedLabel,
        QFrame#SectionCard[active="false"] QLabel#MutedLabel {{
            color: #96A2AF;
        }}

        QFrame#DetailInfo, QFrame#InsetPanel {{
            background-color: {TOKENS["bg_panel"]};
            border: 1px solid {TOKENS["border_soft"]};
            border-radius: {TOKENS["radius_md"]};
        }}

        QFrame#StatusStrip {{
            background-color: {TOKENS["bg_panel_muted"]};
            border: 1px solid {TOKENS["border_soft"]};
            border-radius: {TOKENS["radius_md"]};
        }}

        QGroupBox {{
            background-color: {TOKENS["bg_panel"]};
            border: 1px solid {TOKENS["border_soft"]};
            border-radius: {TOKENS["radius_md"]};
            margin-top: 10px;
        }}

        QGroupBox::title {{
            subcontrol-origin: margin;
            left: 12px;
            padding: 0 4px;
            color: {TOKENS["text_primary"]};
        }}
        """
    )


def build_window_chrome_qss() -> str:
    """自绘窗口标题栏和窗口控制按钮样式。"""
    return section(
        f"""
        QWidget#ChromeShell {{
            background-color: {TOKENS["bg_app"]};
        }}

        QWidget#ChromeContent {{
            background-color: {TOKENS["bg_app"]};
        }}

        QWidget#ChromeTitleBar {{
            background-color: {TOKENS["bg_panel"]};
            border-bottom: 1px solid {TOKENS["border_soft"]};
        }}

        QLabel#ChromeTitle {{
            color: {TOKENS["text_primary"]};
            font-size: 13px;
        }}

        QLabel#ChromeSubtitle {{
            color: {TOKENS["text_tertiary"]};
            font-size: 11px;
        }}

        QPushButton[chromeControl="true"] {{
            background-color: transparent;
            border: 1px solid transparent;
            border-radius: 8px;
            color: {TOKENS["text_secondary"]};
            font-size: 14px;
            padding: 0;
            min-height: 28px;
        }}

        QPushButton[chromeControl="true"]:hover {{
            background-color: {TOKENS["button_hover"]};
            border-color: {TOKENS["border_soft"]};
            color: {TOKENS["text_primary"]};
        }}

        QPushButton[chromeControl="true"]:pressed {{
            background-color: {TOKENS["button_pressed"]};
            border-color: {TOKENS["border_strong"]};
            padding-top: 1px;
        }}

        QPushButton#ChromeCloseButton:hover {{
            background-color: {TOKENS["danger_bg"]};
            border-color: #E4B8B8;
            color: {TOKENS["danger_fg"]};
        }}

        QPushButton#ChromeCloseButton:pressed {{
            background-color: #F0D1D1;
            border-color: #D6A3A3;
            color: {TOKENS["danger_fg"]};
        }}
        """
    )


def build_button_qss() -> str:
    """按钮与交互态样式。"""
    return section(
        f"""
        QPushButton, QToolButton {{
            background-color: {TOKENS["button_bg"]};
            border: 1px solid {TOKENS["border_strong"]};
            border-radius: {TOKENS["radius_sm"]};
            color: {TOKENS["text_primary"]};
            font-weight: 500;
            padding: 6px 12px;
            min-height: 24px;
        }}

        QPushButton:hover, QToolButton:hover {{
            background-color: {TOKENS["button_hover"]};
            border-color: {TOKENS["border_accent"]};
        }}

        QPushButton:pressed, QToolButton:pressed {{
            background-color: {TOKENS["button_pressed"]};
            border-color: {TOKENS["text_tertiary"]};
            padding-top: 7px;
            padding-bottom: 5px;
        }}

        QPushButton:disabled, QToolButton:disabled {{
            color: {TOKENS["button_disabled_text"]};
            background-color: {TOKENS["button_disabled_bg"]};
            border-color: {TOKENS["button_disabled_border"]};
        }}

        QPushButton[variant="primary"],
        QPushButton#PrimaryButton,
        QPushButton#primaryBtn,
        QToolButton[variant="primary"] {{
            background-color: #DCE8F3;
            border-color: #7F95AA;
            color: #24384D;
        }}

        QPushButton[variant="primary"]:hover,
        QPushButton#PrimaryButton:hover,
        QPushButton#primaryBtn:hover,
        QToolButton[variant="primary"]:hover {{
            background-color: #D2E0EC;
            border-color: #6F879E;
        }}

        QPushButton[variant="primary"]:pressed,
        QPushButton#PrimaryButton:pressed,
        QPushButton#primaryBtn:pressed,
        QToolButton[variant="primary"]:pressed {{
            background-color: #C6D7E6;
            border-color: #5F7A93;
            padding-top: 8px;
            padding-bottom: 6px;
        }}

        QPushButton[variant="primary"]:disabled,
        QPushButton#PrimaryButton:disabled,
        QPushButton#primaryBtn:disabled,
        QToolButton[variant="primary"]:disabled {{
            background-color: {TOKENS["button_disabled_primary_bg"]};
            border-color: {TOKENS["button_disabled_primary_bg"]};
            color: {TOKENS["button_disabled_primary_text"]};
        }}

        QPushButton[variant="danger"],
        QPushButton#DangerButton,
        QToolButton[variant="danger"] {{
            background-color: {TOKENS["danger_bg"]};
            border-color: #E0B6B6;
            color: {TOKENS["danger_fg"]};
        }}

        QPushButton[variant="danger"]:hover,
        QPushButton#DangerButton:hover,
        QToolButton[variant="danger"]:hover {{
            background-color: #F4DEDE;
            border-color: #D4A2A2;
        }}

        QPushButton[variant="danger"]:disabled,
        QPushButton#DangerButton:disabled,
        QToolButton[variant="danger"]:disabled {{
            background-color: {TOKENS["button_disabled_danger_bg"]};
            border-color: #E7D9D9;
            color: {TOKENS["button_disabled_danger_text"]};
        }}

        QPushButton[variant="ghost"], QToolButton[variant="ghost"] {{
            background-color: {TOKENS["bg_panel_soft"]};
            border-color: {TOKENS["border_soft"]};
            color: {TOKENS["text_secondary"]};
        }}

        QPushButton[variant="ghost"]:hover, QToolButton[variant="ghost"]:hover {{
            background-color: {TOKENS["button_hover"]};
            border-color: {TOKENS["border_strong"]};
            color: {TOKENS["text_primary"]};
        }}

        QPushButton[variant="ghost"]:disabled, QToolButton[variant="ghost"]:disabled {{
            background-color: {TOKENS["button_disabled_bg"]};
            border-color: {TOKENS["button_disabled_border"]};
            color: {TOKENS["button_disabled_text"]};
        }}

        QPushButton[size="sm"], QToolButton[size="sm"] {{
            min-height: 28px;
            max-height: 32px;
            padding: 5px 10px;
            font-size: 12px;
        }}

        QPushButton[moduleButton="true"] {{
            background-color: {TOKENS["button_bg"]};
            border: 1px solid {TOKENS["border_strong"]};
            border-radius: {TOKENS["radius_sm"]};
            color: #4E5F72;
            font-family: {MODULE_BUTTON_FONT_STACK};
            font-size: 15px;
            font-weight: 550;
            padding: 7px 16px;
            min-height: 42px;
        }}

        QPushButton[moduleButton="true"]:hover {{
            background-color: {TOKENS["button_hover"]};
            border-color: {TOKENS["border_accent"]};
        }}

        QPushButton[moduleButton="true"]:checked {{
            background-color: #DCE8F3;
            border-color: #7F95AA;
            color: #24384D;
        }}

        QPushButton[moduleButton="true"]:checked:hover {{
            background-color: #D2E0EC;
            border-color: #6F879E;
        }}

        QPushButton[moduleButton="true"]:checked:pressed {{
            background-color: #C6D7E6;
            border-color: #5F7A93;
            padding-top: 8px;
            padding-bottom: 6px;
        }}

        QPushButton[moduleButton="true"][actionButton="true"] {{
            background-color: {TOKENS["bg_panel_soft"]};
            color: {TOKENS["text_primary"]};
        }}

        QPushButton[moduleButton="true"]:disabled {{
            background-color: {TOKENS["button_disabled_bg"]};
            border-color: {TOKENS["button_disabled_border"]};
            color: {TOKENS["button_disabled_text"]};
        }}

        QPushButton[routeCompactButton="true"] {{
            background-color: {TOKENS["button_bg"]};
            border: 1px solid {TOKENS["border_strong"]};
            color: {TOKENS["text_primary"]};
            padding: 5px 9px;
            min-height: 28px;
            max-height: 30px;
            border-radius: {TOKENS["radius_sm"]};
            font-size: 12px;
        }}

        QPushButton[routeCompactButton="true"]:hover {{
            background-color: {TOKENS["button_hover"]};
            border-color: {TOKENS["border_accent"]};
        }}

        QPushButton[routeCompactButton="true"]:pressed {{
            background-color: {TOKENS["button_pressed"]};
            border-color: {TOKENS["text_tertiary"]};
        }}

        QPushButton[routeCompactButton="true"]:disabled {{
            background-color: {TOKENS["button_disabled_bg"]};
            border-color: {TOKENS["button_disabled_border"]};
            color: {TOKENS["button_disabled_text"]};
        }}

        QPushButton[routeCompactButton="true"]:checked {{
            background-color: {TOKENS["accent_soft"]};
            border-color: {TOKENS["border_accent"]};
            color: {TOKENS["accent"]};
        }}

        QPushButton[logSourceButton="true"]:checked {{
            background-color: {TOKENS["accent_soft"]};
            border-color: {TOKENS["border_accent"]};
            color: {TOKENS["accent"]};
        }}
        """
    )


def build_form_qss() -> str:
    """输入控件、编辑器和复选框样式。"""
    return section(
        f"""
        QLineEdit, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit, QComboBox {{
            background-color: {TOKENS["bg_panel"]};
            border: 1px solid {TOKENS["border_strong"]};
            border-radius: {TOKENS["radius_sm"]};
            color: {TOKENS["text_primary"]};
            padding: 6px 8px;
            selection-background-color: {TOKENS["selection_bg"]};
            selection-color: {TOKENS["selection_fg"]};
        }}

        QSpinBox, QDoubleSpinBox {{
            padding-right: 30px;
        }}

        QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus,
        QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus {{
            border-color: {TOKENS["accent"]};
        }}

        QSpinBox::up-button, QDoubleSpinBox::up-button {{
            subcontrol-origin: border;
            subcontrol-position: top right;
            width: 24px;
            margin: 1px 1px 0 0;
            border-left: 1px solid {TOKENS["border_soft"]};
            border-bottom: 1px solid {TOKENS["border_soft"]};
            border-top-right-radius: 7px;
            background-color: {TOKENS["bg_panel_muted"]};
        }}

        QSpinBox::down-button, QDoubleSpinBox::down-button {{
            subcontrol-origin: border;
            subcontrol-position: bottom right;
            width: 24px;
            margin: 0 1px 1px 0;
            border-left: 1px solid {TOKENS["border_soft"]};
            border-bottom-right-radius: 7px;
            background-color: {TOKENS["bg_panel_muted"]};
        }}

        QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
        QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
            background-color: {TOKENS["button_hover"]};
        }}

        QSpinBox::up-button:pressed, QDoubleSpinBox::up-button:pressed,
        QSpinBox::down-button:pressed, QDoubleSpinBox::down-button:pressed {{
            background-color: {TOKENS["button_pressed"]};
        }}

        QSpinBox::up-button:disabled, QDoubleSpinBox::up-button:disabled,
        QSpinBox::down-button:disabled, QDoubleSpinBox::down-button:disabled {{
            background-color: {TOKENS["button_disabled_bg"]};
            border-color: {TOKENS["button_disabled_border"]};
        }}

        QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
            image: none;
            width: 0;
            height: 0;
            border-left: 4px solid transparent;
            border-right: 4px solid transparent;
            border-bottom: 5px solid {TOKENS["text_tertiary"]};
        }}

        QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
            image: none;
            width: 0;
            height: 0;
            border-left: 4px solid transparent;
            border-right: 4px solid transparent;
            border-top: 5px solid {TOKENS["text_tertiary"]};
        }}

        QSpinBox::up-arrow:disabled, QDoubleSpinBox::up-arrow:disabled {{
            border-bottom-color: {TOKENS["button_disabled_text"]};
        }}

        QSpinBox::down-arrow:disabled, QDoubleSpinBox::down-arrow:disabled {{
            border-top-color: {TOKENS["button_disabled_text"]};
        }}

        QPlainTextEdit, QTextEdit, QPlainTextEdit#CodePreview {{
            font-family: {MONO_FONT_STACK};
            padding: 8px 10px;
            background-color: {TOKENS["bg_panel"]};
        }}

        QPlainTextEdit#CallResultView {{
            font-family: {UI_FONT_STACK};
            padding: 8px 10px;
            background-color: {TOKENS["bg_panel_soft"]};
        }}

        QComboBox::drop-down {{
            border: none;
            width: 20px;
        }}

        QCheckBox {{
            background-color: transparent;
            color: {TOKENS["text_secondary"]};
            spacing: 8px;
        }}

        QCheckBox::indicator {{
            width: 14px;
            height: 14px;
            border-radius: 4px;
            border: 1px solid {TOKENS["border_strong"]};
            background-color: {TOKENS["bg_panel"]};
        }}

        QCheckBox::indicator:checked {{
            background-color: {TOKENS["accent"]};
            border-color: {TOKENS["accent"]};
        }}
        """
    )


def build_data_qss() -> str:
    """Tabs、表格、树和滚动条样式。"""
    return section(
        f"""
        QTabWidget::pane {{
            border: none;
            background-color: transparent;
            top: 2px;
        }}

        QTabBar::tab {{
            background-color: {TOKENS["neutral_bg"]};
            border: 1px solid {TOKENS["border_soft"]};
            border-radius: {TOKENS["radius_sm"]};
            color: {TOKENS["text_secondary"]};
            padding: 6px 14px;
            margin-right: 6px;
        }}

        QTabBar::tab:hover {{
            background-color: {TOKENS["bg_panel_soft"]};
            color: {TOKENS["text_primary"]};
            border-color: {TOKENS["border_strong"]};
        }}

        QTabBar::tab:selected {{
            background-color: {TOKENS["bg_panel"]};
            color: {TOKENS["accent"]};
            border-color: {TOKENS["border_accent"]};
        }}

        QTableWidget, QTreeWidget, QListWidget {{
            background-color: {TOKENS["bg_panel"]};
            alternate-background-color: {TOKENS["bg_panel_soft"]};
            border: 1px solid {TOKENS["border_soft"]};
            border-radius: {TOKENS["radius_md"]};
            color: {TOKENS["text_primary"]};
            gridline-color: {TOKENS["border_soft"]};
            selection-background-color: {TOKENS["selection_bg"]};
            selection-color: {TOKENS["selection_fg"]};
            outline: 0;
        }}

        QTableWidget::item, QTreeWidget::item, QListWidget::item {{
            padding: 6px;
            border: none;
        }}

        QTableWidget#RegexRulesTable {{
            gridline-color: transparent;
        }}

        QTableWidget#RegexRulesTable::item {{
            padding: 10px 12px;
        }}

        QTableWidget#RegexRulesTable QHeaderView::section {{
            padding: 9px 12px;
        }}

        QTableWidget::item:hover, QTreeWidget::item:hover, QListWidget::item:hover {{
            background-color: {TOKENS["bg_panel_soft"]};
        }}

        QTableWidget::item:selected, QTreeWidget::item:selected, QListWidget::item:selected {{
            background-color: {TOKENS["selection_bg"]};
            color: {TOKENS["selection_fg"]};
        }}

        QFrame#RoutesTreeFrame {{
            background-color: {TOKENS["bg_panel"]};
            border: 1px solid {TOKENS["border_accent"]};
            border-radius: {TOKENS["radius_md"]};
        }}

        QTreeWidget#RoutesTree {{
            background-color: {TOKENS["bg_panel"]};
            alternate-background-color: {TOKENS["bg_panel"]};
            border: none;
            border-radius: {TOKENS["radius_sm"]};
            gridline-color: {TOKENS["border_strong"]};
        }}

        QTreeWidget#RoutesTree::viewport {{
            background-color: {TOKENS["bg_panel"]};
            border-radius: {TOKENS["radius_sm"]};
        }}

        QTreeWidget#RoutesTree::item {{
            background-color: {TOKENS["bg_panel"]};
            padding: 6px 7px;
            border: none;
        }}

        QTreeWidget#RoutesTree::item:hover {{
            background-color: {TOKENS["bg_panel_soft"]};
        }}

        QTreeWidget#RoutesTree::item:selected {{
            background-color: {TOKENS["selection_bg"]};
            color: {TOKENS["selection_fg"]};
        }}

        QTreeWidget#FileBrowserTree {{
            background-color: {TOKENS["bg_panel"]};
            border: 1px solid {TOKENS["border_soft"]};
            border-radius: {TOKENS["radius_md"]};
            padding: 6px;
        }}

        QTreeWidget#FileBrowserTree::item {{
            border-radius: 6px;
            padding: 5px 6px;
            margin: 1px 0;
        }}

        QTreeWidget#FileBrowserTree::item:hover {{
            background-color: {TOKENS["bg_panel_soft"]};
        }}

        QTreeWidget#FileBrowserTree::item:selected {{
            background-color: {TOKENS["selection_bg"]};
            color: {TOKENS["selection_fg"]};
        }}

        QHeaderView::section {{
            background-color: {TOKENS["bg_panel_muted"]};
            color: {TOKENS["text_secondary"]};
            border: none;
            border-bottom: 1px solid {TOKENS["border_soft"]};
            padding: 7px 8px;
        }}

        QSplitter::handle {{
            background-color: {TOKENS["bg_app"]};
        }}

        QScrollArea {{
            border: 0;
            background-color: transparent;
        }}

        QScrollArea > QWidget > QWidget {{
            background-color: transparent;
        }}

        QScrollBar:vertical {{
            background-color: transparent;
            width: 8px;
            margin: 0;
        }}

        QScrollBar::handle:vertical {{
            background-color: {TOKENS["scrollbar"]};
            border-radius: 4px;
            min-height: 24px;
        }}

        QScrollBar::handle:vertical:hover {{
            background-color: {TOKENS["scrollbar_hover"]};
        }}

        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0;
        }}

        QScrollBar:horizontal {{
            background-color: transparent;
            height: 8px;
            margin: 0;
        }}

        QScrollBar::handle:horizontal {{
            background-color: {TOKENS["scrollbar"]};
            border-radius: 4px;
            min-width: 24px;
        }}

        QScrollBar::handle:horizontal:hover {{
            background-color: {TOKENS["scrollbar_hover"]};
        }}

        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
            width: 0;
        }}

        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical,
        QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
            background-color: transparent;
        }}
        """
    )


def build_main_window_qss() -> str:
    """主页面专用柔和背景、顶部按钮和危险按钮覆盖。"""
    return section(
        """
        QWidget#MainWindowRoot {
            background-color: #F3F6FA;
        }

        QWidget#MainWindowRoot QFrame#Toolbar,
        QWidget#MainWindowRoot QFrame#Surface {
            background-color: #FBFCFD;
            border: 1px solid #E3EAF1;
        }

        QWidget#MainWindowRoot QScrollArea,
        QWidget#MainWindowRoot QScrollArea > QWidget > QWidget {
            background-color: transparent;
        }

        QWidget#MainWindowRoot QLabel#PageTitle,
        QWidget#MainWindowRoot QLabel#SectionTitle {
            color: #182430;
        }

        QWidget#MainWindowRoot QPushButton {
            background-color: #F4F7FA;
            border: 1px solid #D7E1EA;
            border-radius: 10px;
            color: #22303D;
        }

        QWidget#MainWindowRoot QPushButton:hover {
            background-color: #EDF3F8;
            border-color: #C5D3E0;
        }

        QWidget#MainWindowRoot QPushButton[moduleButton="true"] {
            background-color: #F6F9FC;
            border: 1px solid #D5E0EA;
            color: #4E5F72;
            font-weight: 580;
        }

        QWidget#MainWindowRoot QPushButton[moduleButton="true"]:checked {
            background-color: #DCE8F3;
            border-color: #7F95AA;
            color: #24384D;
        }

        QWidget#MainWindowRoot QPushButton[moduleButton="true"]:checked:hover {
            background-color: #D2E0EC;
            border-color: #6F879E;
            color: #1C3146;
        }

        QWidget#MainWindowRoot QPushButton[moduleButton="true"]:checked:pressed {
            background-color: #C6D7E6;
            border-color: #5F7A93;
        }

        QWidget#MainWindowRoot QPushButton[variant="danger"] {
            background-color: #F6E5E5;
            border: 1px solid #D9B6B6;
            color: #9C4B4B;
        }

        QWidget#MainWindowRoot QPushButton[variant="danger"]:hover {
            background-color: #F2D9D9;
            border-color: #CC9C9C;
            color: #8D4040;
        }
        """
    )


APP_STYLESHEET = "\n\n".join(
    [
        build_foundation_qss(),
        build_surface_qss(),
        build_window_chrome_qss(),
        build_button_qss(),
        build_form_qss(),
        build_data_qss(),
        build_main_window_qss(),
    ]
)
