"""Alt panel: doğrulama bulguları."""

from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..model.project import KeyRef
from ..services.validator import Issue, Rule, Severity
from .qtutil import combo_enum
from .theme import SEVERITY_COLORS

COLUMNS = ["Önem", "Kural", "Dil", "Dosya", "Anahtar", "Açıklama"]


class IssuesPanel(QWidget):
    issueActivated = Signal(object)  # KeyRef

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.issues: List[Issue] = []

        self.summary = QLabel("Henüz doğrulama yapılmadı")
        self.summary.setStyleSheet("color: #969aa2;")

        self.severity_box = QComboBox()
        self.severity_box.addItem("Tüm önem dereceleri", None)
        for severity in Severity:
            self.severity_box.addItem(severity.label, severity)
        self.severity_box.currentIndexChanged.connect(self._rebuild)

        self.rule_box = QComboBox()
        self.rule_box.addItem("Tüm kurallar", None)
        self.rule_box.currentIndexChanged.connect(self._rebuild)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(False)
        header = self.table.horizontalHeader()
        for column in range(len(COLUMNS) - 1):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(len(COLUMNS) - 1, QHeaderView.Stretch)
        self.table.itemDoubleClicked.connect(self._on_activated)

        top = QHBoxLayout()
        top.setSpacing(6)
        top.addWidget(self.summary, 1)
        top.addWidget(self.severity_box)
        top.addWidget(self.rule_box)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 6)
        layout.setSpacing(5)
        layout.addLayout(top)
        layout.addWidget(self.table, 1)

    # ------------------------------------------------------------------ API

    def set_issues(self, issues: List[Issue]) -> None:
        self.issues = issues
        rules = sorted({issue.rule for issue in issues}, key=lambda r: r.label)
        self.rule_box.blockSignals(True)
        self.rule_box.clear()
        self.rule_box.addItem("Tüm kurallar", None)
        for rule in rules:
            count = sum(1 for issue in issues if issue.rule is rule)
            self.rule_box.addItem(f"{rule.label} ({count})", rule)
        self.rule_box.blockSignals(False)
        self._rebuild()

    def issue_refs(self) -> List[KeyRef]:
        return [issue.ref for issue in self.issues if issue.key]

    # -------------------------------------------------------------- yardımcı

    def _rebuild(self) -> None:
        severity = combo_enum(self.severity_box, Severity)
        rule = combo_enum(self.rule_box, Rule)
        rows = [
            issue
            for issue in self.issues
            if (severity is None or issue.severity is severity)
            and (rule is None or issue.rule is rule)
        ]

        self.table.setRowCount(len(rows))
        for index, issue in enumerate(rows):
            values = [
                issue.severity.label,
                issue.rule.label,
                issue.lang,
                issue.bundle,
                issue.key,
                issue.message,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setForeground(SEVERITY_COLORS[issue.severity.value])
                item.setData(Qt.UserRole, issue.ref if issue.key else None)
                self.table.setItem(index, column, item)

        errors = sum(1 for i in self.issues if i.severity is Severity.ERROR)
        warnings = sum(1 for i in self.issues if i.severity is Severity.WARNING)
        infos = len(self.issues) - errors - warnings
        if not self.issues:
            self.summary.setText("Bulgu yok — her şey temiz")
        else:
            self.summary.setText(
                f"{len(self.issues)} bulgu · {errors} hata, {warnings} uyarı, "
                f"{infos} bilgi  (gösterilen: {len(rows)})"
            )

    def _on_activated(self, item: QTableWidgetItem) -> None:
        ref = item.data(Qt.UserRole)
        if ref is not None:
            self.issueActivated.emit(ref)
