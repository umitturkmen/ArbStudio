"""TXT dışa aktarma diyaloğu."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Sequence

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from ...model.project import KeyRef, Project
from ...txtio import ExportFormat, export_txt
from ..qtutil import combo_enum


class ExportDialog(QDialog):
    def __init__(
        self,
        project: Project,
        current_bundle: str = "",
        selected_refs: Optional[Sequence[KeyRef]] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("TXT olarak dışa aktar")
        self.setMinimumWidth(560)
        self.project = project
        self.selected_refs = list(selected_refs or [])
        self.result_path: Optional[Path] = None

        self.lang_box = QComboBox()
        for lang in project.languages:
            suffix = "  (kaynak)" if lang == project.source_lang else ""
            self.lang_box.addItem(lang + suffix, lang)
        self.lang_box.setCurrentIndex(project.languages.index(project.source_lang))

        self.scope_box = QComboBox()
        self.scope_box.addItem(
            f"Tüm proje ({project.key_count} anahtar)", ("all", "")
        )
        for bundle in sorted(project.bundles):
            count = len(project.keys_of(bundle))
            self.scope_box.addItem(f"{bundle} ({count} anahtar)", ("bundle", bundle))
        if self.selected_refs:
            self.scope_box.insertItem(
                0,
                f"Listede seçili anahtarlar ({len(self.selected_refs)})",
                ("selection", ""),
            )
            self.scope_box.setCurrentIndex(0)
        elif current_bundle:
            for index in range(self.scope_box.count()):
                if self.scope_box.itemData(index) == ("bundle", current_bundle):
                    self.scope_box.setCurrentIndex(index)
                    break

        self.format_box = QComboBox()
        for fmt in ExportFormat:
            self.format_box.addItem(fmt.label, fmt)

        self.path_edit = QLineEdit()
        browse = QPushButton("Gözat…")
        browse.clicked.connect(self._browse)
        path_row = QHBoxLayout()
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(browse)

        self.manifest_check = QCheckBox(
            "Eşleme manifesti (.arbmap.json) yaz — geri yüklerken hizalama denetlenir"
        )
        self.manifest_check.setChecked(True)

        hint = QLabel(
            "Satır bazlı modda satır N = anahtar N. Gerçek satır sonları \\n olarak "
            "kaçırılır; çeviride \\n gördüğün yere satır sonu koy."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #969aa2;")

        form = QFormLayout()
        form.addRow("Dil:", self.lang_box)
        form.addRow("Kapsam:", self.scope_box)
        form.addRow("Biçim:", self.format_box)
        form.addRow("Dosya:", path_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Dışa Aktar")
        buttons.accepted.connect(self._export)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.manifest_check)
        layout.addWidget(hint)
        layout.addSpacing(4)
        layout.addWidget(buttons)

        self.lang_box.currentIndexChanged.connect(self._suggest_path)
        self.scope_box.currentIndexChanged.connect(self._suggest_path)
        self._suggest_path()

    # -------------------------------------------------------------- yardımcı

    def _refs(self) -> List[KeyRef]:
        kind, bundle = self.scope_box.currentData()
        if kind == "selection":
            return self.selected_refs
        if kind == "bundle":
            return self.project.keys_of(bundle)
        return list(self.project.key_order)

    def _suggest_path(self) -> None:
        lang = self.lang_box.currentData()
        kind, bundle = self.scope_box.currentData()
        stem = Path(bundle).stem if kind == "bundle" else "tum"
        name = f"{lang}_{stem}.txt"
        self.path_edit.setText(str(self.project.root.parent / name))

    def _browse(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Dışa aktarılacak dosya", self.path_edit.text(), "Metin (*.txt)"
        )
        if path:
            self.path_edit.setText(path)

    def _export(self) -> None:
        path = self.path_edit.text().strip()
        if not path:
            QMessageBox.warning(self, "Eksik bilgi", "Bir dosya yolu seçin.")
            return
        refs = self._refs()
        if not refs:
            QMessageBox.warning(self, "Boş kapsam", "Seçilen kapsamda anahtar yok.")
            return
        try:
            result = export_txt(
                self.project,
                self.lang_box.currentData(),
                refs,
                Path(path),
                combo_enum(self.format_box, ExportFormat, ExportFormat.LINES),
                write_manifest=self.manifest_check.isChecked(),
            )
        except Exception as exc:  # sessiz kalmaktansa nedeni göster
            QMessageBox.critical(
                self,
                "Dışa aktarılamadı",
                f"{type(exc).__name__}: {exc}\n\n"
                f"TXT kısmen yazılmış olabilir: {path}",
            )
            return

        self.result_path = result.txt_path
        message = (
            f"{result.line_count} satır yazıldı.\n{result.txt_path}"
            + (f"\n\nManifest: {result.manifest_path.name}" if result.manifest_path else "")
            + (
                f"\n\nNot: {result.empty_count} anahtar bu dilde boş — "
                "TXT'de boş satır olarak yer alıyor."
                if result.empty_count
                else ""
            )
        )
        QMessageBox.information(self, "Dışa aktarıldı", message)
        self.accept()
