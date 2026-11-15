"""Sol panel: filtreli, sanal anahtar listesi."""

from __future__ import annotations

from enum import Enum
from typing import List, Optional, Sequence, Set

from PySide6.QtCore import QAbstractListModel, QModelIndex, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from ..model.keyinfo import KeyStatus, placeholders
from ..model.project import KeyRef, Project
from .qtutil import combo_enum
from .theme import STATUS_COLORS, TEXT_DIM

REF_ROLE = Qt.UserRole + 1
STATUS_ROLE = Qt.UserRole + 2
BUNDLE_ROLE = Qt.UserRole + 3
ISSUE_ROLE = Qt.UserRole + 4


class FilterMode(str, Enum):
    ALL = "all"
    UNTRANSLATED = "untranslated"
    SAME = "same"
    WITH_PLACEHOLDER = "placeholder"
    PROBLEM = "problem"

    @property
    def label(self) -> str:
        return {
            FilterMode.ALL: "Tümü",
            FilterMode.UNTRANSLATED: "Çevrilmemiş",
            FilterMode.SAME: "Kaynakla aynı",
            FilterMode.WITH_PLACEHOLDER: "Yer tutuculu",
            FilterMode.PROBLEM: "Sorunlu",
        }[self]


class KeyListModel(QAbstractListModel):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.project: Optional[Project] = None
        self.rows: List[KeyRef] = []
        self._issue_refs: Set[KeyRef] = set()
        self._search = ""
        self._bundle = ""
        self._mode = FilterMode.ALL

    # ------------------------------------------------------------ Qt arayüzü

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or self.project is None:
            return None
        ref = self.rows[index.row()]
        if role == Qt.DisplayRole:
            return ref.key
        if role == REF_ROLE:
            return ref
        if role == BUNDLE_ROLE:
            return ref.bundle.removesuffix(".arb")
        if role == STATUS_ROLE:
            return self.project.worst_status(ref)
        if role == ISSUE_ROLE:
            return ref in self._issue_refs
        if role == Qt.ToolTipRole:
            source = self.project.source_value(ref)
            return f"{ref.bundle} · {ref.key}\n{source[:200]}"
        return None

    # -------------------------------------------------------------- yenileme

    def set_project(self, project: Optional[Project]) -> None:
        self.project = project
        self.refresh()

    def set_issue_refs(self, refs: Sequence[KeyRef]) -> None:
        self._issue_refs = set(refs)
        self.refresh()

    def set_filters(
        self,
        search: Optional[str] = None,
        bundle: Optional[str] = None,
        mode: Optional[FilterMode] = None,
    ) -> None:
        if search is not None:
            self._search = search.strip().lower()
        if bundle is not None:
            self._bundle = bundle
        if mode is not None:
            self._mode = mode
        self.refresh()

    def refresh(self) -> None:
        self.beginResetModel()
        self.rows = list(self._compute_rows())
        self.endResetModel()

    def _compute_rows(self):
        if self.project is None:
            return
        project = self.project
        targets = [l for l in project.languages if l != project.source_lang]
        for ref in project.key_order:
            if self._bundle and ref.bundle != self._bundle:
                continue
            if self._search and not self._matches_search(ref):
                continue
            if not self._matches_mode(ref, targets):
                continue
            yield ref

    def _matches_search(self, ref: KeyRef) -> bool:
        if self._search in ref.key.lower():
            return True
        assert self.project is not None
        for lang in self.project.languages:
            value = self.project.value(ref, lang)
            if value and self._search in value.lower():
                return True
        return False

    def _matches_mode(self, ref: KeyRef, targets: Sequence[str]) -> bool:
        assert self.project is not None
        if self._mode is FilterMode.ALL:
            return True
        if self._mode is FilterMode.PROBLEM:
            return ref in self._issue_refs
        if self._mode is FilterMode.WITH_PLACEHOLDER:
            return bool(placeholders(self.project.source_value(ref)))
        wanted = (
            KeyStatus.MISSING
            if self._mode is FilterMode.UNTRANSLATED
            else KeyStatus.SAME_AS_SOURCE
        )
        return any(self.project.status(ref, lang) is wanted for lang in targets)

    def row_of(self, ref: KeyRef) -> int:
        try:
            return self.rows.index(ref)
        except ValueError:
            return -1


class KeyItemDelegate(QStyledItemDelegate):
    """Durum noktası + anahtar adı + sağda soluk dosya rozeti."""

    DOT = 8

    def sizeHint(self, option, index) -> QSize:
        return QSize(option.rect.width(), 24)

    def paint(self, painter: QPainter, option, index) -> None:
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        rect = option.rect

        if option.state & QStyle.State_Selected:
            painter.fillRect(rect, QColor(52, 81, 126))
        elif option.state & QStyle.State_MouseOver:
            painter.fillRect(rect, QColor(42, 44, 49))

        status = index.data(STATUS_ROLE)
        color = STATUS_COLORS.get(status, QColor(120, 120, 120))
        painter.setBrush(color)
        painter.setPen(Qt.NoPen)
        dot_y = rect.y() + (rect.height() - self.DOT) // 2
        painter.drawEllipse(rect.x() + 7, dot_y, self.DOT, self.DOT)

        bundle = index.data(BUNDLE_ROLE) or ""
        font = QFont(option.font)
        font.setPointSizeF(max(7.0, option.font.pointSizeF() - 1.5))
        painter.setFont(font)
        metrics = painter.fontMetrics()
        bundle_w = metrics.horizontalAdvance(bundle) + 8
        painter.setPen(TEXT_DIM)
        painter.drawText(
            QRect(rect.right() - bundle_w, rect.y(), bundle_w - 4, rect.height()),
            Qt.AlignRight | Qt.AlignVCenter,
            bundle,
        )

        painter.setFont(option.font)
        painter.setPen(QColor(222, 224, 228))
        text_rect = QRect(
            rect.x() + 22, rect.y(), rect.width() - 26 - bundle_w, rect.height()
        )
        elided = painter.fontMetrics().elidedText(
            index.data(Qt.DisplayRole) or "", Qt.ElideMiddle, text_rect.width()
        )
        painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, elided)

        if index.data(ISSUE_ROLE):
            painter.setPen(QColor(224, 176, 72))
            painter.drawText(
                QRect(rect.x() + 22, rect.y(), rect.width() - 26, rect.height()),
                Qt.AlignRight | Qt.AlignVCenter,
                "",
            )
        painter.restore()


class KeyListPanel(QWidget):
    """Arama kutusu + dosya seçici + filtre + liste."""

    currentKeyChanged = Signal(object)  # KeyRef | None

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.model = KeyListModel(self)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Anahtar veya metin ara…  (Ctrl+F)")
        self.search.setClearButtonEnabled(True)

        self.bundle_box = QComboBox()
        self.mode_box = QComboBox()
        for mode in FilterMode:
            self.mode_box.addItem(mode.label, mode)

        self.view = QListView()
        self.view.setModel(self.model)
        self.view.setItemDelegate(KeyItemDelegate(self.view))
        self.view.setUniformItemSizes(True)
        self.view.setMouseTracking(True)
        self.view.setSelectionMode(QListView.ExtendedSelection)

        self.count_label = QLabel("—")
        self.count_label.setStyleSheet("color: #969aa2; padding: 3px 6px;")

        filters = QHBoxLayout()
        filters.setContentsMargins(0, 0, 0, 0)
        filters.setSpacing(4)
        filters.addWidget(self.bundle_box, 1)
        filters.addWidget(self.mode_box, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 3, 6)
        layout.setSpacing(5)
        layout.addWidget(self.search)
        layout.addLayout(filters)
        layout.addWidget(self.view, 1)
        layout.addWidget(self.count_label)

        self.search.textChanged.connect(self._on_search)
        self.bundle_box.currentIndexChanged.connect(self._on_bundle)
        self.mode_box.currentIndexChanged.connect(self._on_mode)
        self.view.selectionModel().currentChanged.connect(self._on_current)
        self.model.modelReset.connect(self._update_count)

    # ------------------------------------------------------------------ API

    def set_project(self, project: Optional[Project]) -> None:
        self.bundle_box.blockSignals(True)
        self.bundle_box.clear()
        self.bundle_box.addItem("Tüm dosyalar", "")
        if project is not None:
            for bundle in sorted(project.bundles):
                self.bundle_box.addItem(bundle, bundle)
        self.bundle_box.blockSignals(False)
        self.model.set_project(project)

    def selected_refs(self) -> List[KeyRef]:
        return [
            index.data(REF_ROLE) for index in self.view.selectionModel().selectedIndexes()
        ]

    def current_ref(self) -> Optional[KeyRef]:
        index = self.view.currentIndex()
        return index.data(REF_ROLE) if index.isValid() else None

    def select_ref(self, ref: KeyRef) -> bool:
        row = self.model.row_of(ref)
        if row < 0:
            # Anahtar mevcut filtreye takılıyorsa filtreyi gevşet.
            self.mode_box.setCurrentIndex(0)
            self.search.clear()
            row = self.model.row_of(ref)
            if row < 0:
                self.bundle_box.setCurrentIndex(0)
                row = self.model.row_of(ref)
        if row < 0:
            return False
        index = self.model.index(row, 0)
        self.view.setCurrentIndex(index)
        self.view.scrollTo(index, QListView.PositionAtCenter)
        return True

    def next_untranslated(self) -> None:
        if self.model.project is None:
            return
        project = self.model.project
        start = self.view.currentIndex().row() + 1
        order = list(range(start, len(self.model.rows))) + list(range(0, start))
        for row in order:
            if project.worst_status(self.model.rows[row]) is not KeyStatus.TRANSLATED:
                index = self.model.index(row, 0)
                self.view.setCurrentIndex(index)
                self.view.scrollTo(index, QListView.PositionAtCenter)
                return

    def refresh_current_row(self) -> None:
        index = self.view.currentIndex()
        if index.isValid():
            self.model.dataChanged.emit(index, index)

    def focus_search(self) -> None:
        self.search.setFocus()
        self.search.selectAll()

    # -------------------------------------------------------------- slotlar

    def _on_search(self, text: str) -> None:
        self.model.set_filters(search=text)

    def _on_bundle(self) -> None:
        self.model.set_filters(bundle=self.bundle_box.currentData() or "")

    def _on_mode(self) -> None:
        self.model.set_filters(
            mode=combo_enum(self.mode_box, FilterMode, FilterMode.ALL)
        )

    def _on_current(self, current: QModelIndex) -> None:
        self.currentKeyChanged.emit(current.data(REF_ROLE) if current.isValid() else None)

    def _update_count(self) -> None:
        total = self.model.project.key_count if self.model.project else 0
        shown = len(self.model.rows)
        if shown == total:
            self.count_label.setText(f"{total} anahtar")
        else:
            self.count_label.setText(f"{shown} / {total} anahtar")
