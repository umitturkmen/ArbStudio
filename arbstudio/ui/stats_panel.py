"""İstatistik paneli: dil × dosya tamamlanma matrisi."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..model.project import Project


def _percent_color(percent: float) -> QColor:
    if percent >= 99.5:
        return QColor(96, 184, 112)
    if percent >= 75:
        return QColor(180, 190, 100)
    if percent >= 40:
        return QColor(224, 176, 72)
    return QColor(224, 88, 88)


class StatsPanel(QWidget):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.table = QTableWidget(0, 0)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(self.table)

    def update_stats(self, project: Optional[Project]) -> None:
        if project is None or not project.languages:
            self.table.setRowCount(0)
            self.table.setColumnCount(0)
            return

        targets = [l for l in project.languages if l != project.source_lang]
        bundles = sorted(project.bundles)
        rows = bundles + ["TOPLAM"]

        self.table.setColumnCount(len(targets) + 1)
        self.table.setHorizontalHeaderLabels(
            ["Dosya"] + [f"{lang}  (%)" for lang in targets]
        )
        self.table.setRowCount(len(rows))

        stats = {lang: project.stats(lang) for lang in targets}
        for row, bundle in enumerate(rows):
            key = "__total__" if bundle == "TOPLAM" else bundle
            name = QTableWidgetItem(bundle)
            if bundle == "TOPLAM":
                font = name.font()
                font.setBold(True)
                name.setFont(font)
            self.table.setItem(row, 0, name)

            for column, lang in enumerate(targets, start=1):
                stat = stats[lang][key]
                item = QTableWidgetItem(
                    f"{stat.percent:.1f}%   ({stat.translated}/{stat.total})"
                )
                item.setTextAlignment(Qt.AlignCenter)
                item.setForeground(_percent_color(stat.percent))
                item.setToolTip(
                    f"çevrildi {stat.translated} · kaynakla aynı {stat.same} · "
                    f"eksik {stat.missing}"
                )
                if bundle == "TOPLAM":
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                self.table.setItem(row, column, item)

        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        for column in range(1, self.table.columnCount()):
            header.setSectionResizeMode(column, QHeaderView.Stretch)
