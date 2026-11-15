"""Sağ panel: seçili anahtarın dil başına düzenleyicileri."""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..model.keyinfo import KeyStatus, placeholders, plural_group
from ..model.project import KeyRef, Project
from .theme import STATUS_COLORS

_PLACEHOLDER_RE = re.compile(r"\{\w+\}")


class PlaceholderHighlighter(QSyntaxHighlighter):
    """`{count}` gibi yer tutucuları vurgular."""

    def __init__(self, document):
        super().__init__(document)
        self._format = QTextCharFormat()
        self._format.setForeground(QColor(230, 180, 90))
        self._format.setFontWeight(QFont.Bold)

    def highlightBlock(self, text: str) -> None:
        for match in _PLACEHOLDER_RE.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self._format)


class ValueEditor(QPlainTextEdit):
    """Tek dil için değer kutusu. Enter yeni satır ekler."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTabChangesFocus(True)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._highlighter = PlaceholderHighlighter(self.document())
        self.document().documentLayout().documentSizeChanged.connect(self._autosize)
        self._autosize()

    def _autosize(self, *_) -> None:
        height = int(self.document().size().height() * self.fontMetrics().lineSpacing())
        self.setFixedHeight(max(34, min(height + 14, 220)))


class EditorPanel(QWidget):
    """Bir anahtarı (veya çoğul grubunu) tüm dillerde düzenler."""

    valueEdited = Signal(object, str, str)  # KeyRef, lang, value
    renameRequested = Signal(object)
    deleteRequested = Signal(object)
    moveRequested = Signal(object)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.project: Optional[Project] = None
        self.refs: List[KeyRef] = []
        self._editors: Dict[Tuple[KeyRef, str], ValueEditor] = {}
        self._status_labels: Dict[Tuple[KeyRef, str], QLabel] = {}
        self._loading = False

        self.title = QLabel("Bir anahtar seçin")
        title_font = QFont()
        title_font.setPointSize(12)
        title_font.setBold(True)
        self.title.setFont(title_font)
        self.title.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self.subtitle = QLabel("")
        self.subtitle.setStyleSheet("color: #969aa2;")

        self.btn_rename = QPushButton("Yeniden adlandır")
        self.btn_move = QPushButton("Taşı")
        self.btn_delete = QPushButton("Sil")
        for button in (self.btn_rename, self.btn_move, self.btn_delete):
            button.setEnabled(False)
        self.btn_rename.clicked.connect(lambda: self._emit(self.renameRequested))
        self.btn_move.clicked.connect(lambda: self._emit(self.moveRequested))
        self.btn_delete.clicked.connect(lambda: self._emit(self.deleteRequested))

        header_text = QVBoxLayout()
        header_text.setSpacing(1)
        header_text.addWidget(self.title)
        header_text.addWidget(self.subtitle)

        header = QHBoxLayout()
        header.addLayout(header_text, 1)
        header.addWidget(self.btn_rename)
        header.addWidget(self.btn_move)
        header.addWidget(self.btn_delete)

        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 8, 0)
        self.body_layout.setSpacing(10)
        self.body_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setWidget(self.body)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(9, 6, 6, 6)
        layout.setSpacing(8)
        layout.addLayout(header)
        layout.addWidget(scroll, 1)

    # ------------------------------------------------------------------ API

    def set_project(self, project: Optional[Project]) -> None:
        self.project = project
        self.show_key(None)

    def show_key(self, ref: Optional[KeyRef]) -> None:
        self._clear()
        if self.project is None or ref is None:
            self.title.setText("Bir anahtar seçin")
            self.subtitle.setText("")
            for button in (self.btn_rename, self.btn_move, self.btn_delete):
                button.setEnabled(False)
            return

        for button in (self.btn_rename, self.btn_move, self.btn_delete):
            button.setEnabled(True)

        self.refs = self._group_refs(ref)
        group = plural_group(ref.key)
        if group and len(self.refs) > 1:
            self.title.setText(group[0])
            self.subtitle.setText(
                f"{ref.bundle} · çoğul grubu ({len(self.refs)} kategori)"
            )
        else:
            self.title.setText(ref.key)
            self.subtitle.setText(ref.bundle)

        self._loading = True
        for item in self.refs:
            self.body_layout.insertWidget(
                self.body_layout.count() - 1, self._build_card(item)
            )
        self._loading = False

    def focus_first_target(self) -> None:
        if self.project is None:
            return
        for (ref, lang), editor in self._editors.items():
            if lang != self.project.source_lang:
                editor.setFocus()
                return

    def refresh_values(self) -> None:
        """Model dışarıdan değiştiyse kutuları tazeler (imleci korumaya çalışır)."""
        if self.project is None:
            return
        self._loading = True
        for (ref, lang), editor in self._editors.items():
            value = self.project.value(ref, lang) or ""
            if editor.toPlainText() != value:
                editor.setPlainText(value)
            self._update_status(ref, lang)
        self._loading = False

    # -------------------------------------------------------------- yardımcı

    def _group_refs(self, ref: KeyRef) -> List[KeyRef]:
        assert self.project is not None
        group = plural_group(ref.key)
        if not group:
            return [ref]
        base = group[0]
        members = [
            item
            for item in self.project.key_order
            if item.bundle == ref.bundle
            and (pg := plural_group(item.key))
            and pg[0] == base
        ]
        return members or [ref]

    def _clear(self) -> None:
        self._editors.clear()
        self._status_labels.clear()
        self.refs = []
        while self.body_layout.count() > 1:
            item = self.body_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _build_card(self, ref: KeyRef) -> QWidget:
        assert self.project is not None
        project = self.project
        box = QGroupBox(ref.key)
        layout = QVBoxLayout(box)
        layout.setSpacing(6)

        ordered = [project.source_lang] + [
            lang for lang in project.languages if lang != project.source_lang
        ]
        for lang in ordered:
            layout.addLayout(self._build_row(ref, lang))
        return box

    def _build_row(self, ref: KeyRef, lang: str) -> QVBoxLayout:
        assert self.project is not None
        is_source = lang == self.project.source_lang

        name = QLabel(lang.upper() + ("  (kaynak)" if is_source else ""))
        name.setFixedWidth(110)
        name.setStyleSheet(
            "color: %s; font-weight: bold;" % ("#7fa8e8" if is_source else "#c8ccd4")
        )

        status = QLabel("")
        status.setStyleSheet("color: #969aa2;")
        self._status_labels[(ref, lang)] = status

        head = QHBoxLayout()
        head.setSpacing(6)
        head.addWidget(name)
        head.addWidget(status, 1)

        editor = ValueEditor()
        editor.setPlainText(self.project.value(ref, lang) or "")
        editor.setReadOnly(is_source)
        if not is_source:
            editor.textChanged.connect(
                lambda r=ref, l=lang, e=editor: self._on_text_changed(r, l, e)
            )
        self._editors[(ref, lang)] = editor

        row = QVBoxLayout()
        row.setSpacing(2)
        row.addLayout(head)
        row.addWidget(editor)
        self._update_status(ref, lang)
        return row

    def _on_text_changed(self, ref: KeyRef, lang: str, editor: ValueEditor) -> None:
        if self._loading:
            return
        self.valueEdited.emit(ref, lang, editor.toPlainText())
        self._update_status(ref, lang)

    def _update_status(self, ref: KeyRef, lang: str) -> None:
        if self.project is None:
            return
        label = self._status_labels.get((ref, lang))
        editor = self._editors.get((ref, lang))
        if label is None or editor is None:
            return

        if lang == self.project.source_lang:
            names = sorted(placeholders(editor.toPlainText()))
            label.setText(
                "yer tutucu: " + ", ".join("{%s}" % n for n in names) if names else ""
            )
            return

        source = self.project.source_value(ref)
        value = editor.toPlainText()
        expected, actual = placeholders(source), placeholders(value)
        problem = expected != actual and bool(value)

        editor.setProperty("phError", "true" if problem else "false")
        editor.style().unpolish(editor)
        editor.style().polish(editor)

        if problem:
            missing = sorted(expected - actual)
            extra = sorted(actual - expected)
            parts = []
            if missing:
                parts.append("eksik " + ", ".join("{%s}" % n for n in missing))
            if extra:
                parts.append("fazla " + ", ".join("{%s}" % n for n in extra))
            label.setText("⚠ yer tutucu: " + "; ".join(parts))
            label.setStyleSheet("color: #e05858;")
            return

        status = (
            KeyStatus.MISSING
            if not value.strip()
            else (
                KeyStatus.SAME_AS_SOURCE
                if value == source and source
                else KeyStatus.TRANSLATED
            )
        )
        text = {
            KeyStatus.MISSING: "çevrilmemiş",
            KeyStatus.SAME_AS_SOURCE: "kaynakla aynı",
            KeyStatus.TRANSLATED: "çevrildi",
        }[status]
        label.setText(text)
        label.setStyleSheet("color: %s;" % STATUS_COLORS[status].name())

    def _emit(self, signal: Signal) -> None:
        if self.refs:
            signal.emit(self.refs[0])
