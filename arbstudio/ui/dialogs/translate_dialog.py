"""Claude API ile toplu çeviri diyaloğu — arka planda çalışır, önizleme ile onaylanır."""

from __future__ import annotations

from typing import List, Optional, Sequence

from PySide6.QtCore import QObject, QSettings, Qt, QThread, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ...model.keyinfo import KeyStatus
from ...model.project import KeyRef, Project
from ...services.translator import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_MODEL,
    TranslationResult,
    TranslatorError,
    estimate_cost,
    language_name,
    resolve_api_key,
    translate_batches,
)


class _Worker(QObject):
    progressed = Signal(int, int, str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, project, refs, lang, api_key, model, batch_size):
        super().__init__()
        self.args = (project, refs, lang, api_key, model, batch_size)
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        project, refs, lang, api_key, model, batch_size = self.args
        try:
            result = translate_batches(
                project,
                refs,
                lang,
                api_key,
                model=model,
                batch_size=batch_size,
                progress=lambda done, total, note: self.progressed.emit(done, total, note),
                should_cancel=lambda: self._cancel,
            )
        except TranslatorError as exc:
            self.failed.emit(str(exc))
            return
        except Exception as exc:  # ağ/SDK kaynaklı beklenmeyen hata
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        self.finished.emit(result)


class TranslateDialog(QDialog):
    def __init__(
        self,
        project: Project,
        settings: QSettings,
        current_bundle: str = "",
        selected_refs: Optional[Sequence[KeyRef]] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Claude ile çevir")
        self.resize(980, 640)
        self.project = project
        self.settings = settings
        self.selected_refs = list(selected_refs or [])
        self.result: Optional[TranslationResult] = None
        self.applied = 0
        self._thread: Optional[QThread] = None
        self._worker: Optional[_Worker] = None

        self.lang_box = QComboBox()
        for lang in project.languages:
            if lang != project.source_lang:
                self.lang_box.addItem(f"{lang} — {language_name(lang)}", lang)

        self.scope_box = QComboBox()
        self.scope_box.addItem("Yalnızca çevrilmemiş anahtarlar", ("untranslated", ""))
        self.scope_box.addItem("Çevrilmemiş + kaynakla aynı olanlar", ("stale", ""))
        self.scope_box.addItem("Tüm proje (mevcut çevirilerin üzerine öneri)", ("all", ""))
        for bundle in sorted(project.bundles):
            self.scope_box.addItem(f"{bundle} — çevrilmemişler", ("bundle", bundle))
        if self.selected_refs:
            self.scope_box.insertItem(
                0, f"Listede seçili anahtarlar ({len(self.selected_refs)})", ("selection", "")
            )
        elif current_bundle:
            for index in range(self.scope_box.count()):
                if self.scope_box.itemData(index) == ("bundle", current_bundle):
                    self.scope_box.setCurrentIndex(index)
                    break

        self.model_label = QLabel("")
        self.scope_label = QLabel("")
        self.scope_label.setStyleSheet("color: #969aa2;")

        self.start_btn = QPushButton("Çeviriyi başlat")
        self.start_btn.setProperty("accent", "true")
        self.start_btn.clicked.connect(self._start)
        self.cancel_btn = QPushButton("Durdur")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel)

        self.progress = QProgressBar()
        self.progress.setVisible(False)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color: #969aa2;")

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Uygula", "Anahtar", "Kaynak", "Öneri", "Mevcut"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)

        self.check_all = QPushButton("Tümünü seç")
        self.check_none = QPushButton("Tümünü bırak")
        self.check_all.clicked.connect(lambda: self._set_all(True))
        self.check_none.clicked.connect(lambda: self._set_all(False))
        for button in (self.check_all, self.check_none):
            button.setEnabled(False)

        form = QFormLayout()
        form.addRow("Hedef dil:", self.lang_box)
        form.addRow("Kapsam:", self.scope_box)
        form.addRow("Model:", self.model_label)

        controls = QHBoxLayout()
        controls.addWidget(self.check_all)
        controls.addWidget(self.check_none)
        controls.addStretch(1)
        controls.addWidget(self.start_btn)
        controls.addWidget(self.cancel_btn)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText("Seçilenleri uygula")
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(False)
        self.buttons.accepted.connect(self._apply)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.scope_label)
        layout.addLayout(controls)
        layout.addWidget(self.progress)
        layout.addWidget(self.status)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.buttons)

        self.lang_box.currentIndexChanged.connect(self._update_scope_label)
        self.scope_box.currentIndexChanged.connect(self._update_scope_label)
        self._update_model_label()
        self._update_scope_label()

    # -------------------------------------------------------------- yardımcı

    def _model(self) -> str:
        return self.settings.value("api/model", DEFAULT_MODEL, str)

    def _update_model_label(self) -> None:
        key = resolve_api_key(self.settings.value("api/key", "", str))
        state = "anahtar tanımlı" if key else "<b style='color:#e05858'>API anahtarı yok</b>"
        self.model_label.setText(f"{self._model()} · {state}")
        self.start_btn.setEnabled(bool(key) and self.lang_box.count() > 0)

    def _refs(self) -> List[KeyRef]:
        kind, bundle = self.scope_box.currentData()
        lang = self.lang_box.currentData()
        if kind == "selection":
            return self.selected_refs
        if kind == "all":
            return list(self.project.key_order)
        pool = (
            self.project.keys_of(bundle) if kind == "bundle" else list(self.project.key_order)
        )
        if kind == "stale":
            return [
                ref
                for ref in pool
                if self.project.status(ref, lang) is not KeyStatus.TRANSLATED
            ]
        return [
            ref for ref in pool if self.project.status(ref, lang) is KeyStatus.MISSING
        ]

    def _update_scope_label(self) -> None:
        count = len(self._refs())
        batch = int(self.settings.value("api/batch", DEFAULT_BATCH_SIZE))
        requests = (count + batch - 1) // batch if count else 0
        self.scope_label.setText(
            f"{count} anahtar · yaklaşık {requests} API isteği "
            f"({batch}'lik gruplar hâlinde)"
        )

    # ---------------------------------------------------------------- çeviri

    def _start(self) -> None:
        refs = self._refs()
        if not refs:
            QMessageBox.information(
                self, "Boş kapsam", "Seçilen kapsamda çevrilecek anahtar yok."
            )
            return
        api_key = resolve_api_key(self.settings.value("api/key", "", str))
        if not api_key:
            QMessageBox.warning(self, "API anahtarı yok", "Önce ayarlardan anahtar girin.")
            return

        self.table.setRowCount(0)
        self.progress.setVisible(True)
        self.progress.setRange(0, len(refs))
        self.progress.setValue(0)
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.status.setText("Çeviri başlatıldı…")

        self._thread = QThread(self)
        self._worker = _Worker(
            self.project,
            refs,
            self.lang_box.currentData(),
            api_key,
            self._model(),
            int(self.settings.value("api/batch", DEFAULT_BATCH_SIZE)),
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progressed.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._thread.start()

    def _cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self.status.setText("Durduruluyor — süren istek tamamlanınca kesilecek…")
            self.cancel_btn.setEnabled(False)

    def _on_progress(self, done: int, total: int, note: str) -> None:
        self.progress.setValue(done)
        self.status.setText(f"{done}/{total} anahtar işlendi — {note}")

    def _on_failed(self, message: str) -> None:
        self._teardown()
        self.status.setText(f"<span style='color:#e05858'>Hata: {message}</span>")

    def _on_finished(self, result: TranslationResult) -> None:
        self._teardown()
        self.result = result
        self._fill_table(result)

        cost = estimate_cost(result.input_tokens, result.output_tokens, self._model())
        parts = [
            f"{len(result.suggestions)} öneri",
            f"{result.input_tokens:,} girdi + {result.output_tokens:,} çıktı token",
            f"≈ ${cost:.3f}",
        ]
        text = " · ".join(parts)
        if result.cancelled:
            text = "Durduruldu. " + text
        if result.invalid_count:
            text += (
                f"<br><span style='color:#e0b048'>⚠ {result.invalid_count} öneride "
                "yer tutucu uyuşmuyor — bunlar varsayılan olarak seçili değil.</span>"
            )
        if result.errors:
            shown = "<br>".join(result.errors[:5])
            more = f"<br>… ve {len(result.errors) - 5} tane daha" if len(result.errors) > 5 else ""
            text += f"<br><span style='color:#e05858'>{shown}{more}</span>"
        self.status.setText(text)

        has_rows = bool(result.suggestions)
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(has_rows)
        self.check_all.setEnabled(has_rows)
        self.check_none.setEnabled(has_rows)

    def _teardown(self) -> None:
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(5000)
            self._thread = None
        self._worker = None
        self.progress.setVisible(False)
        self.cancel_btn.setEnabled(False)
        self.start_btn.setEnabled(True)

    def _fill_table(self, result: TranslationResult) -> None:
        self.table.setRowCount(len(result.suggestions))
        for row, item in enumerate(result.suggestions):
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            check.setCheckState(Qt.Checked if item.is_valid else Qt.Unchecked)
            check.setData(Qt.UserRole, row)
            self.table.setItem(row, 0, check)

            values = [
                item.ref.key,
                item.source.replace("\n", "\\n"),
                item.proposed.replace("\n", "\\n"),
                item.current.replace("\n", "\\n"),
            ]
            for column, value in enumerate(values, start=1):
                cell = QTableWidgetItem(value)
                if item.placeholder_issue:
                    cell.setBackground(QColor(60, 34, 34))
                    cell.setToolTip("Yer tutucu sorunu: " + item.placeholder_issue)
                self.table.setItem(row, column, cell)

    def _set_all(self, checked: bool) -> None:
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is not None:
                item.setCheckState(Qt.Checked if checked else Qt.Unchecked)

    def _apply(self) -> None:
        if self.result is None:
            return
        lang = self.lang_box.currentData()
        applied = 0
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is None or item.checkState() != Qt.Checked:
                continue
            suggestion = self.result.suggestions[item.data(Qt.UserRole)]
            if self.project.set_value(suggestion.ref, lang, suggestion.proposed):
                applied += 1
        self.applied = applied
        self.accept()

    def reject(self) -> None:
        if self._thread is not None:
            self._cancel()
            self._thread.quit()
            self._thread.wait(5000)
        super().reject()
