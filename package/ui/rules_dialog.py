"""提供正则规则新增、编辑、删除和保存弹窗。"""

from __future__ import annotations

import copy
import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from package.ui.window_chrome import ChromeDialog


REGEX_RULE_DIALOG_MIN_WIDTH = 1040
REGEX_RULE_DIALOG_MIN_HEIGHT = 620
REGEX_RULE_ROW_HEIGHT = 44


class RuleEditDialog(ChromeDialog):
    def __init__(
        self,
        rule: dict | None = None,
        existing_names: set[str] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """初始化正则规则编辑窗口。"""
        super().__init__(parent)
        self.setWindowTitle("编辑正则规则" if rule else "新增正则规则")
        self.setModal(True)
        self.existing_names = existing_names or set()

        root = self.content_layout()
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        name_label = QLabel("规则名称")
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("例如：登录接口")
        root.addWidget(name_label)
        root.addWidget(self.name_input)

        pattern_label = QLabel("正则表达式")
        self.pattern_input = QPlainTextEdit()
        self.pattern_input.setObjectName("CodePreview")
        self.pattern_input.setPlaceholderText(r"例如：/api/login|/passport/auth")
        self.pattern_input.setMinimumHeight(86)
        root.addWidget(pattern_label)
        root.addWidget(self.pattern_input)

        note_label = QLabel("备注")
        self.note_input = QPlainTextEdit()
        self.note_input.setObjectName("CodePreview")
        self.note_input.setMinimumHeight(72)
        root.addWidget(note_label)
        root.addWidget(self.note_input)

        self.enabled_input = QCheckBox("启用规则")
        self.enabled_input.setChecked(True)
        root.addWidget(self.enabled_input)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.setMinimumWidth(520)

        if rule:
            self.name_input.setText(str(rule.get("name", "")))
            self.original_name = str(rule.get("name", ""))
            self.pattern_input.setPlainText(str(rule.get("pattern", "")))
            self.note_input.setPlainText(str(rule.get("note", "")))
            self.enabled_input.setChecked(bool(rule.get("enabled", True)))
        else:
            self.original_name = ""

    def accept(self) -> None:
        """校验规则输入并关闭窗口。"""
        name = self.name_input.text().strip()
        pattern = self.pattern_input.toPlainText().strip()
        if not name:
            QMessageBox.warning(self, "无法保存", "规则名称不能为空。")
            return
        if name != self.original_name and name in self.existing_names:
            QMessageBox.warning(self, "无法保存", "规则名称已存在。")
            return
        if not pattern:
            QMessageBox.warning(self, "无法保存", "正则表达式不能为空。")
            return
        try:
            re.compile(pattern)
        except re.error as exc:
            QMessageBox.warning(self, "无法保存", f"正则表达式无效：{exc}")
            return
        super().accept()

    def rule_data(self) -> dict:
        """返回当前窗口中的正则规则数据。"""
        return {
            "name": self.name_input.text().strip(),
            "pattern": self.pattern_input.toPlainText().strip(),
            "enabled": self.enabled_input.isChecked(),
            "note": self.note_input.toPlainText().strip(),
        }


class RegexRulesDialog(ChromeDialog):
    rules_saved = Signal(list)

    def __init__(self, rules: list[dict], parent: QWidget | None = None) -> None:
        """初始化正则规则管理窗口。"""
        super().__init__(parent)
        self.setWindowTitle("正则规则配置")
        self.setModal(True)
        self.rules = copy.deepcopy(rules)

        root = self.content_layout()
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel("正则规则")
        title.setObjectName("SectionTitle")
        header.addWidget(title)
        self.rule_count_label = QLabel()
        self.rule_count_label.setObjectName("MutedLabel")
        header.addWidget(self.rule_count_label)
        header.addItem(QSpacerItem(10, 10, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))

        self.add_button = QPushButton("新增")
        self.add_button.setProperty("variant", "primary")
        self.add_button.clicked.connect(self.add_rule)
        header.addWidget(self.add_button)

        self.edit_button = QPushButton("编辑")
        self.edit_button.setProperty("variant", "ghost")
        self.edit_button.clicked.connect(self.edit_selected_rule)
        header.addWidget(self.edit_button)

        self.delete_button = QPushButton("删除")
        self.delete_button.setProperty("variant", "danger")
        self.delete_button.clicked.connect(self.delete_selected_rule)
        header.addWidget(self.delete_button)
        root.addLayout(header)

        self.table = QTableWidget(0, 4)
        self.table.setObjectName("RegexRulesTable")
        self.table.setHorizontalHeaderLabels(["启用", "名称", "正则表达式", "备注"])
        self.configure_table_layout()
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.table.setShowGrid(False)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.doubleClicked.connect(self.edit_selected_rule)
        root.addWidget(self.table, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.save_rules)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.setMinimumSize(REGEX_RULE_DIALOG_MIN_WIDTH, REGEX_RULE_DIALOG_MIN_HEIGHT)
        self.populate_table()

    def configure_table_layout(self) -> None:
        """配置规则表格的行高、列宽和表头，缓解长正则表达式拥挤。"""
        vertical_header = self.table.verticalHeader()
        vertical_header.setVisible(False)
        vertical_header.setMinimumSectionSize(REGEX_RULE_ROW_HEIGHT)
        vertical_header.setDefaultSectionSize(REGEX_RULE_ROW_HEIGHT)

        header = self.table.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(0, 72)
        self.table.setColumnWidth(1, 190)
        self.table.setColumnWidth(3, 260)

    def make_table_item(self, text: str, *, alignment: Qt.AlignmentFlag | None = None) -> QTableWidgetItem:
        """创建带完整 tooltip 的表格项，长文本被截断时仍可查看全量内容。"""
        item = QTableWidgetItem(str(text or ""))
        item.setToolTip(str(text or ""))
        if alignment is not None:
            item.setTextAlignment(alignment)
        return item

    def refresh_rule_count(self) -> None:
        """刷新标题旁的规则数量提示。"""
        self.rule_count_label.setText(f"{len(self.rules)} 条规则")

    def populate_table(self) -> None:
        """把规则列表填充到表格中。"""
        self.table.setRowCount(len(self.rules))
        for row, rule in enumerate(self.rules):
            enabled = self.make_table_item(
                "启用" if rule.get("enabled") else "停用",
                alignment=Qt.AlignmentFlag.AlignCenter,
            )
            self.table.setItem(row, 0, enabled)
            self.table.setItem(row, 1, self.make_table_item(str(rule.get("name", ""))))
            self.table.setItem(row, 2, self.make_table_item(str(rule.get("pattern", ""))))
            self.table.setItem(row, 3, self.make_table_item(str(rule.get("note", ""))))
            self.table.setRowHeight(row, REGEX_RULE_ROW_HEIGHT)
        self.refresh_rule_count()

    def selected_row(self) -> int:
        """获取当前选中的规则行号。"""
        selected = self.table.selectionModel().selectedRows()
        return selected[0].row() if selected else -1

    def existing_names(self, exclude_row: int = -1) -> set[str]:
        """获取已有规则名称集合，用于去重校验。"""
        names = set()
        for index, rule in enumerate(self.rules):
            if index == exclude_row:
                continue
            name = str(rule.get("name", "")).strip()
            if name:
                names.add(name)
        return names

    def add_rule(self) -> None:
        """新增一条正则规则。"""
        dialog = RuleEditDialog(existing_names=self.existing_names(), parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.rules.append(dialog.rule_data())
            self.populate_table()
            self.table.selectRow(len(self.rules) - 1)

    def edit_selected_rule(self) -> None:
        """编辑当前选中的正则规则。"""
        row = self.selected_row()
        if row < 0:
            QMessageBox.information(self, "请选择规则", "请先选择一条规则。")
            return
        dialog = RuleEditDialog(
            self.rules[row],
            existing_names=self.existing_names(exclude_row=row),
            parent=self,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.rules[row] = dialog.rule_data()
            self.populate_table()
            self.table.selectRow(row)

    def delete_selected_rule(self) -> None:
        """删除当前选中的正则规则。"""
        row = self.selected_row()
        if row < 0:
            QMessageBox.information(self, "请选择规则", "请先选择一条规则。")
            return
        name = str(self.rules[row].get("name", ""))
        reply = QMessageBox.question(
            self,
            "删除规则",
            f"确认删除规则「{name}」？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.rules.pop(row)
            self.populate_table()

    def save_rules(self) -> None:
        """保存规则列表并通知主窗口。"""
        self.rules_saved.emit(copy.deepcopy(self.rules))
        self.accept()
