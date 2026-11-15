"""TXT içe aktarma diyaloğu — analiz, uyarılar, önizleme, uygulama."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Sequence

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ...model.project import KeyRef, Project
from ...txtio import ImportAction, ImportPlan, build_import_plan

ACTION_COLORS = {
    ImportAction.NEW: QColor(96, 184, 112),
    ImportAction.CHANGED: QColor(224, 176, 72),
    ImportAction.UNCHANGED: QColor(140, 144, 152),
    ImportAction.SKIPPED_EMPTY: QColor(140, 144, 152),
    ImportAction.UNKNOWN_KEY: QColor(224, 88, 88),
}


class ImportDialog(QDialog):
    def __init__(
        self,
        project: Project,
        current_bundle: str = "",
        selected_refs: Optional[Sequence[KeyRef]] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("TXT'den içe aktar")
        self.resize(940, 620)
        self.project = project
        self.selected_refs = list(selected_refs or [])
        self.plan: Optional[ImportPlan] = None
        self.applied = 0

        self.path_edit = QLineEdit()
        browse = QPushButton("Gözat…")
        browse.clicked.connect(self._browse)
        path_row = QHBoxLayout()
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(browse)

        self.lang_box = QComboBox()
        for lang in project.languages:
            if lang != project.source_lang:
                self.lang_box.addItem(lang, lang)
        if self.lang_box.count() == 0:
            for lang in project.languages:
                self.lang_box.addItem(lang, lang)

        self.scope_box = QComboBox()
        self.scope_box.addItem("Tüm proje (manifest yoksa bu sıra kullanılır)", ("all", ""))
        for bundle in sorted(project.bundles):
            self.scope_box.addItem(bundle, ("bundle", bundle))
        if self.selected_refs:
            self.scope_box.insertItem(
                0, f"Listede seçili anahtarlar ({len(self.selected_refs)})", ("selection", "")
            )
        elif current_bundle:
            for index in range(self.scope_box.count()):
                if self.scope_box.itemData(index) == ("bundle", current_bundle):
                    self.scope_box.setCurrentIndex(index)
                    break

        self.write_empty = QCheckBox(
            "Boş satırları da yaz (varsayılan: boş satır mevcut çeviriyi korur)"
        )
        self.use_manifest = QCheckBox("Yanındaki .arbmap.json manifestini kullan")
        self.use_manifest.setChecked(True)

        self.analyze_btn = QPushButton("Çözümle")
        self.analyze_btn.setProperty("accent", "true")
        self.analyze_btn.clicked.connect(self._analyze)

        self.status = QLabel("Bir TXT dosyası seçip Çözümle'ye basın.")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color: #969aa2;")

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Satır", "Anahtar", "Kaynak", "Yeni değer", "Durum"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)

        form = QFormLayout()
        form.addRow("TXT dosyası:", path_row)
        form.addRow("Hedef dil:", self.lang_box)
        form.addRow("Kapsam:", self.scope_box)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText("Uygula")
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(False)
        self.buttons.accepted.connect(self._apply)
        self.buttons.rejected.connect(self.reject)

        top_row = QHBoxLayout()
        top_row.addStretch(1)
        top_row.addWidget(self.analyze_btn)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.write_empty)
        layout.addWidget(self.use_manifest)
        layout.addLayout(top_row)
        layout.addWidget(self.status)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.buttons)

    # -------------------------------------------------------------- yardımcı

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "İçe aktarılacak TXT", str(self.project.root.parent), "Metin (*.txt);;Tümü (*)"
        )
        if path:
            self.path_edit.setText(path)
            self._analyze()

    def _scope_refs(self) -> Optional[List[KeyRef]]:
        kind, bundle = self.scope_box.currentData()
        if kind == "selection":
            return self.selected_refs
        if kind == "bundle":
            return self.project.keys_of(bundle)
        return None

    def _analyze(self) -> None:
        path = self.path_edit.text().strip()
        if not path or not Path(path).exists():
            QMessageBox.warning(self, "Dosya yok", "Geçerli bir TXT dosyası seçin.")
            return
        try:
            self.plan = build_import_plan(
                self.project,
                self.lang_box.currentData(),
                Path(path),
                scope_refs=self._scope_refs(),
                write_empty=self.write_empty.isChecked(),
                use_manifest=self.use_manifest.isChecked(),
            )
        except (OSError, UnicodeDecodeError) as exc:
            QMessageBox.critical(self, "Okunamadı", str(exc))
            return

        self._fill_table(self.plan)
        self.status.setText(self._summary(self.plan))
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(bool(self.plan.writable_rows))

    def _summary(self, plan: ImportPlan) -> str:
        counts = plan.counts()
        parts = [
            f"Biçim: <b>{'satır bazlı' if plan.fmt.value == 'lines' else 'TSV'}</b>",
            f"{plan.line_count} satır / {plan.expected_count} beklenen anahtar",
            f"manifest: {'kullanıldı' if plan.manifest_used else 'yok'}",
        ]
        head = " · ".join(parts)

        detail = (
            f"<br>yeni {counts[ImportAction.NEW]} · "
            f"değişen {counts[ImportAction.CHANGED]} · "
            f"aynı {counts[ImportAction.UNCHANGED]} · "
            f"boş-atlanan {counts[ImportAction.SKIPPED_EMPTY]}"
        )
        if counts[ImportAction.UNKNOWN_KEY]:
            detail += f" · <b>bilinmeyen {counts[ImportAction.UNKNOWN_KEY]}</b>"
        if plan.untouched_keys:
            detail += f" · dokunulmayan {len(plan.untouched_keys)}"

        warnings = []
        for text in plan.warnings:
            warnings.append(text)
        if plan.count_mismatch and plan.fmt.value == "lines":
            diff = plan.line_count - plan.expected_count
            warnings.append(
                f"Satır sayısı uyuşmuyor: TXT'de {'fazla' if diff > 0 else 'eksik'} "
                f"{abs(diff)} satır var. Hizalama kaymış olabilir."
            )
        if plan.divergence is not None:
            d = plan.divergence
            warnings.append(
                f"Sapmanın yakalandığı ilk satır: <b>{d.line_no}</b> ('{d.key}') — "
                f"{d.reason}<br>"
                f"&nbsp;&nbsp;kaynak: {d.source[:70]}<br>"
                f"&nbsp;&nbsp;gelen: {d.imported[:70]}<br>"
                "&nbsp;&nbsp;<i>Yalnızca yer tutuculu satırlar sinyal verir; "
                "kayma birkaç satır daha erken başlamış olabilir.</i>"
            )
        if plan.suspicious_count:
            warnings.append(
                f"{plan.suspicious_count} satırda yer tutucu kaynakla uyuşmuyor."
            )

        if warnings:
            return (
                f"{head}{detail}<br><br>"
                "<span style='color:#e0b048;'><b>⚠ Dikkat</b><br>"
                + "<br>".join(warnings)
                + "</span>"
            )
        return f"<span style='color:#60b870;'>✓</span> {head}{detail}"

    def _fill_table(self, plan: ImportPlan) -> None:
        self.table.setRowCount(len(plan.rows))
        for index, row in enumerate(plan.rows):
            values = [
                str(row.line_no),
                row.raw_key or (row.ref.key if row.ref else ""),
                row.source.replace("\n", "\\n"),
                row.new.replace("\n", "\\n"),
                row.action.label + (f" ⚠ {row.placeholder_issue}" if row.placeholder_issue else ""),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 4:
                    item.setForeground(ACTION_COLORS[row.action])
                if row.placeholder_issue:
                    item.setBackground(QColor(60, 34, 34))
                item.setData(Qt.UserRole, row.ref)
                self.table.setItem(index, column, item)

    def _apply(self) -> None:
        if self.plan is None:
            return
        if self.plan.is_risky:
            answer = QMessageBox.warning(
                self,
                "Riskli içe aktarma",
                "Çözümleme hizalama sorunu veya bilinmeyen anahtarlar buldu.\n\n"
                "Yine de uygulansın mı? (Dosyalar diske ancak Kaydet dediğinizde yazılır.)",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
        self.applied = self.plan.apply(self.project)
        self.accept()
