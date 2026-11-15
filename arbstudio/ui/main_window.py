"""ARB Studio ana penceresi."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QTabWidget,
    QToolBar,
    QWidget,
)

from .. import APP_NAME, ORG_NAME, __version__
from ..model.project import KeyRef, Project
from ..services.validator import Rule, Severity, validate
from .dialogs import (
    AddKeyDialog,
    ApiSettingsDialog,
    ExportDialog,
    ImportDialog,
    MoveKeyDialog,
    NewLanguageDialog,
    TranslateDialog,
)
from .editor_panel import EditorPanel
from .issues_panel import IssuesPanel
from .key_list import KeyListPanel
from .stats_panel import StatsPanel

MAX_RECENT = 8


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings(ORG_NAME, APP_NAME)
        self.project: Optional[Project] = None

        self.setWindowTitle(APP_NAME)
        self.resize(1380, 860)

        self.key_panel = KeyListPanel()
        self.editor = EditorPanel()
        self.issues = IssuesPanel()
        self.stats = StatsPanel()

        self.bottom_tabs = QTabWidget()
        self.bottom_tabs.addTab(self.issues, "Doğrulama")
        self.bottom_tabs.addTab(self.stats, "İstatistik")

        self.right_split = QSplitter(Qt.Vertical)
        self.right_split.addWidget(self.editor)
        self.right_split.addWidget(self.bottom_tabs)
        self.right_split.setStretchFactor(0, 3)
        self.right_split.setStretchFactor(1, 2)

        self.main_split = QSplitter(Qt.Horizontal)
        self.main_split.addWidget(self.key_panel)
        self.main_split.addWidget(self.right_split)
        self.main_split.setStretchFactor(0, 1)
        self.main_split.setStretchFactor(1, 3)
        self.main_split.setSizes([340, 1040])
        self.setCentralWidget(self.main_split)

        self.source_box = QComboBox()
        self.source_box.setMinimumWidth(150)
        self.source_box.currentIndexChanged.connect(self._on_source_changed)

        self.status_label = QLabel("Proje açılmadı")
        self.statusBar().addWidget(self.status_label, 1)
        self.dirty_label = QLabel("")
        self.statusBar().addPermanentWidget(self.dirty_label)

        self._build_actions()
        self._build_toolbar()
        self._build_menu()
        self._connect()
        self._restore_state()
        self._update_enabled()

    # ------------------------------------------------------------ kurulum

    def _build_actions(self) -> None:
        def make(text, slot, shortcut=None, tip=None):
            action = QAction(text, self)
            action.triggered.connect(slot)
            if shortcut:
                action.setShortcut(QKeySequence(shortcut))
            action.setToolTip(tip or text)
            return action

        self.act_open = make("Proje Aç", self.open_project, "Ctrl+O")
        self.act_reload = make("Yeniden Yükle", self.reload_project, "F5")
        self.act_save = make("Kaydet", self.save_project, "Ctrl+S")
        self.act_export = make("Dışa Aktar (TXT)", self.export_txt, "Ctrl+E")
        self.act_import = make("İçe Aktar (TXT)", self.import_txt, "Ctrl+I")
        self.act_add_key = make("Anahtar Ekle", self.add_key, "Ctrl+N")
        self.act_rename_key = make("Yeniden Adlandır", self.rename_key, "F2")
        self.act_delete_key = make("Anahtarı Sil", self.delete_key)
        self.act_move_key = make("Anahtarı Taşı", self.move_key)
        self.act_new_lang = make("Yeni Dil", self.new_language)
        self.act_validate = make("Doğrula", self.run_validation, "Ctrl+R")
        self.act_translate = make("Çevir (AI)", self.translate)
        self.act_api = make("Çeviri Ayarları", self.api_settings)
        self.act_find = make("Ara", self.key_panel.focus_search, "Ctrl+F")
        self.act_next_todo = make(
            "Sonraki Çevrilmemiş", self.key_panel.next_untranslated, "Ctrl+Return"
        )
        self.act_quit = make("Çıkış", self.close, "Ctrl+Q")
        self.act_about = make("Hakkında", self.show_about)

    def _build_toolbar(self) -> None:
        bar = QToolBar("Ana")
        bar.setMovable(False)
        bar.setToolButtonStyle(Qt.ToolButtonTextOnly)
        for action in (self.act_open, self.act_save):
            bar.addAction(action)
        bar.addSeparator()
        bar.addWidget(QLabel("  Kaynak dil: "))
        bar.addWidget(self.source_box)
        bar.addSeparator()
        for action in (self.act_export, self.act_import):
            bar.addAction(action)
        bar.addSeparator()
        for action in (self.act_add_key, self.act_new_lang):
            bar.addAction(action)
        bar.addSeparator()
        for action in (self.act_validate, self.act_translate):
            bar.addAction(action)
        self.addToolBar(bar)

    def _build_menu(self) -> None:
        menu = self.menuBar()

        file_menu = menu.addMenu("&Dosya")
        file_menu.addAction(self.act_open)
        self.recent_menu = file_menu.addMenu("Son Projeler")
        file_menu.addAction(self.act_reload)
        file_menu.addSeparator()
        file_menu.addAction(self.act_save)
        file_menu.addSeparator()
        file_menu.addAction(self.act_export)
        file_menu.addAction(self.act_import)
        file_menu.addSeparator()
        file_menu.addAction(self.act_quit)

        edit_menu = menu.addMenu("&Düzen")
        edit_menu.addAction(self.act_find)
        edit_menu.addAction(self.act_next_todo)
        edit_menu.addSeparator()
        edit_menu.addAction(self.act_add_key)
        edit_menu.addAction(self.act_rename_key)
        edit_menu.addAction(self.act_move_key)
        edit_menu.addAction(self.act_delete_key)

        tools_menu = menu.addMenu("&Araçlar")
        tools_menu.addAction(self.act_new_lang)
        tools_menu.addAction(self.act_validate)
        tools_menu.addSeparator()
        tools_menu.addAction(self.act_translate)
        tools_menu.addAction(self.act_api)

        help_menu = menu.addMenu("&Yardım")
        help_menu.addAction(self.act_about)
        self._refresh_recent_menu()

    def _connect(self) -> None:
        self.key_panel.currentKeyChanged.connect(self.editor.show_key)
        self.editor.valueEdited.connect(self._on_value_edited)
        self.editor.renameRequested.connect(lambda ref: self.rename_key(ref))
        self.editor.deleteRequested.connect(lambda ref: self.delete_key(ref))
        self.editor.moveRequested.connect(lambda ref: self.move_key(ref))
        self.issues.issueActivated.connect(self._jump_to)

    # -------------------------------------------------------------- durumlar

    def _update_enabled(self) -> None:
        has = self.project is not None
        for action in (
            self.act_reload,
            self.act_save,
            self.act_export,
            self.act_import,
            self.act_add_key,
            self.act_rename_key,
            self.act_delete_key,
            self.act_move_key,
            self.act_new_lang,
            self.act_validate,
            self.act_translate,
        ):
            action.setEnabled(has)
        self._update_status()

    def _update_status(self) -> None:
        if self.project is None:
            self.status_label.setText("Proje açılmadı")
            self.dirty_label.setText("")
            self.setWindowTitle(APP_NAME)
            return
        project = self.project
        self.status_label.setText(
            f"{project.root}   ·   {len(project.languages)} dil "
            f"({', '.join(project.languages)})   ·   {len(project.bundles)} dosya   ·   "
            f"{project.key_count} anahtar"
        )
        dirty = project.dirty_files
        self.dirty_label.setText(
            f"● {len(dirty)} dosya kaydedilmedi" if dirty else "kaydedildi"
        )
        self.dirty_label.setStyleSheet(
            "color: #e0b048;" if dirty else "color: #60b870;"
        )
        self.setWindowTitle(
            f"{APP_NAME} — {project.root.name}{' *' if dirty else ''}"
        )

    # ------------------------------------------------------------ proje aç

    def open_project(self) -> None:
        start = self.settings.value("last_dir", str(Path.home()), str)
        path = QFileDialog.getExistingDirectory(
            self, "ARB dosyalarının bulunduğu klasörü seçin", start
        )
        if path:
            self.load_project(Path(path))

    def load_project(self, root: Path) -> None:
        if not self._confirm_discard():
            return
        try:
            saved_source = self.settings.value(self._source_key(root), "", str)
            project = Project.scan(root, saved_source or None)
        except OSError as exc:
            QMessageBox.critical(self, "Açılamadı", str(exc))
            return

        if not project.bundles:
            QMessageBox.warning(
                self,
                "ARB bulunamadı",
                f"{root} altında (alt klasörler dâhil) hiç .arb dosyası yok.",
            )
            return

        self.project = project
        self.settings.setValue("last_dir", str(root))
        self._push_recent(root)

        self.source_box.blockSignals(True)
        self.source_box.clear()
        for lang in project.languages:
            self.source_box.addItem(lang, lang)
        self.source_box.setCurrentIndex(project.languages.index(project.source_lang))
        self.source_box.blockSignals(False)

        self.key_panel.set_project(project)
        self.editor.set_project(project)
        self.issues.set_issues([])
        self.stats.update_stats(project)
        self._update_enabled()

        if project.load_errors:
            QMessageBox.warning(
                self,
                "Bazı dosyalar atlandı",
                "\n".join(project.load_errors[:12]),
            )
        self.run_validation()

    def reload_project(self) -> None:
        if self.project is None:
            return
        if not self._confirm_discard():
            return
        self.load_project(self.project.root)

    @staticmethod
    def _source_key(root: Path) -> str:
        """QSettings anahtarı — yol ayırıcıları grup ayırıcısıyla çakışmasın."""
        digest = hashlib.sha1(str(root).encode("utf-8")).hexdigest()[:16]
        return f"source_lang/{digest}"

    def _push_recent(self, root: Path) -> None:
        recent: List[str] = list(self.settings.value("recent", [], list) or [])
        text = str(root)
        if text in recent:
            recent.remove(text)
        recent.insert(0, text)
        self.settings.setValue("recent", recent[:MAX_RECENT])
        self._refresh_recent_menu()

    def _refresh_recent_menu(self) -> None:
        self.recent_menu.clear()
        recent = list(self.settings.value("recent", [], list) or [])
        if not recent:
            action = self.recent_menu.addAction("(yok)")
            action.setEnabled(False)
            return
        for path in recent:
            action = self.recent_menu.addAction(path)
            action.triggered.connect(lambda _=False, p=path: self.load_project(Path(p)))

    def _on_source_changed(self) -> None:
        if self.project is None:
            return
        lang = self.source_box.currentData()
        if not lang or lang == self.project.source_lang:
            return
        self.project.source_lang = lang
        self.project.rebuild_key_order()
        self.settings.setValue(self._source_key(self.project.root), lang)
        self.key_panel.model.refresh()
        self.editor.show_key(self.key_panel.current_ref())
        self.stats.update_stats(self.project)
        self.run_validation()

    # ------------------------------------------------------------- kaydetme

    def save_project(self) -> None:
        if self.project is None:
            return
        try:
            saved = self.project.save_all()
        except OSError as exc:
            QMessageBox.critical(self, "Kaydedilemedi", str(exc))
            return
        self._update_status()
        self.statusBar().showMessage(
            f"{len(saved)} dosya kaydedildi" if saved else "Değişiklik yoktu", 4000
        )
        self.run_validation()

    def _confirm_discard(self) -> bool:
        if self.project is None or not self.project.is_dirty:
            return True
        answer = QMessageBox.question(
            self,
            "Kaydedilmemiş değişiklikler",
            f"{len(self.project.dirty_files)} dosyada kaydedilmemiş değişiklik var.\n"
            "Kaydedilsin mi?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Save,
        )
        if answer == QMessageBox.Cancel:
            return False
        if answer == QMessageBox.Save:
            self.save_project()
        return True

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._confirm_discard():
            event.ignore()
            return
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("window_state", self.saveState())
        self.settings.setValue("main_split", self.main_split.saveState())
        self.settings.setValue("right_split", self.right_split.saveState())
        event.accept()

    def _restore_state(self) -> None:
        for key, setter in (
            ("geometry", self.restoreGeometry),
            ("window_state", self.restoreState),
            ("main_split", self.main_split.restoreState),
            ("right_split", self.right_split.restoreState),
        ):
            value = self.settings.value(key)
            if value:
                setter(value)

    # ------------------------------------------------------------ düzenleme

    def _on_value_edited(self, ref: KeyRef, lang: str, value: str) -> None:
        if self.project is None:
            return
        if self.project.set_value(ref, lang, value):
            self.key_panel.refresh_current_row()
            self._update_status()

    def add_key(self) -> None:
        if self.project is None:
            return
        current = self.key_panel.current_ref()
        dialog = AddKeyDialog(self.project, current.bundle if current else "", self)
        if dialog.exec() and dialog.created:
            self.key_panel.model.refresh()
            self.key_panel.select_ref(dialog.created)
            self.editor.focus_first_target()
            self._after_structure_change()

    def rename_key(self, ref: Optional[KeyRef] = None) -> None:
        if self.project is None:
            return
        ref = ref if isinstance(ref, KeyRef) else self.key_panel.current_ref()
        if ref is None:
            return
        new_key, ok = QInputDialog.getText(
            self, "Yeniden adlandır", f"{ref.bundle} içindeki yeni anahtar adı:", text=ref.key
        )
        if not ok or not new_key.strip() or new_key == ref.key:
            return
        renamed = self.project.rename_key(ref, new_key.strip())
        self.key_panel.model.refresh()
        self.key_panel.select_ref(renamed)
        self._after_structure_change()

    def delete_key(self, ref: Optional[KeyRef] = None) -> None:
        if self.project is None:
            return
        ref = ref if isinstance(ref, KeyRef) else self.key_panel.current_ref()
        if ref is None:
            return
        langs = [
            lang
            for lang in self.project.languages
            if self.project.value(ref, lang) is not None
        ]
        answer = QMessageBox.question(
            self,
            "Anahtarı sil",
            f"'{ref.key}' anahtarı {ref.bundle} içinde {len(langs)} dilden silinecek "
            f"({', '.join(langs)}).\n\nDevam edilsin mi?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self.project.delete_key(ref)
        self.key_panel.model.refresh()
        self.editor.show_key(self.key_panel.current_ref())
        self._after_structure_change()

    def move_key(self, ref: Optional[KeyRef] = None) -> None:
        if self.project is None:
            return
        ref = ref if isinstance(ref, KeyRef) else self.key_panel.current_ref()
        if ref is None or len(self.project.bundles) < 2:
            return
        dialog = MoveKeyDialog(self.project, ref, self)
        if dialog.exec() and dialog.moved:
            self.key_panel.model.refresh()
            self.key_panel.select_ref(dialog.moved)
            self._after_structure_change()

    def new_language(self) -> None:
        if self.project is None:
            return
        dialog = NewLanguageDialog(self.project, self)
        if not dialog.exec() or not dialog.created_lang:
            return
        self.source_box.blockSignals(True)
        self.source_box.clear()
        for lang in self.project.languages:
            self.source_box.addItem(lang, lang)
        self.source_box.setCurrentIndex(
            self.project.languages.index(self.project.source_lang)
        )
        self.source_box.blockSignals(False)
        self.key_panel.model.refresh()
        self.editor.show_key(self.key_panel.current_ref())
        self._after_structure_change()

    def _after_structure_change(self) -> None:
        self.stats.update_stats(self.project)
        self._update_status()
        self.run_validation()

    # -------------------------------------------------------- TXT / çeviri

    def export_txt(self) -> None:
        if self.project is None:
            return
        ExportDialog(
            self.project,
            self.key_panel.bundle_box.currentData() or "",
            self.key_panel.selected_refs(),
            self,
        ).exec()

    def import_txt(self) -> None:
        if self.project is None:
            return
        dialog = ImportDialog(
            self.project,
            self.key_panel.bundle_box.currentData() or "",
            self.key_panel.selected_refs(),
            self,
        )
        if dialog.exec():
            self.editor.refresh_values()
            self.key_panel.model.refresh()
            self._after_structure_change()
            self.statusBar().showMessage(
                f"{dialog.applied} değer içe aktarıldı — kaydetmek için Ctrl+S", 8000
            )

    def translate(self) -> None:
        if self.project is None:
            return
        if len(self.project.languages) < 2:
            QMessageBox.information(
                self, "Hedef dil yok", "Önce 'Yeni Dil' ile bir hedef dil ekleyin."
            )
            return
        dialog = TranslateDialog(
            self.project,
            self.settings,
            self.key_panel.bundle_box.currentData() or "",
            self.key_panel.selected_refs(),
            self,
        )
        if dialog.exec():
            self.editor.refresh_values()
            self.key_panel.model.refresh()
            self._after_structure_change()
            self.statusBar().showMessage(
                f"{dialog.applied} çeviri uygulandı — kaydetmek için Ctrl+S", 8000
            )

    def api_settings(self) -> None:
        ApiSettingsDialog(self.settings, self).exec()

    # ------------------------------------------------------------ doğrulama

    def run_validation(self) -> None:
        if self.project is None:
            return
        issues = validate(self.project)
        self.issues.set_issues(issues)
        self.key_panel.model.set_issue_refs(self.issues.issue_refs())
        errors = sum(1 for issue in issues if issue.severity is Severity.ERROR)
        placeholder = sum(1 for issue in issues if issue.rule is Rule.PLACEHOLDER)
        if errors:
            self.bottom_tabs.setTabText(0, f"Doğrulama ({errors} hata)")
        else:
            self.bottom_tabs.setTabText(0, f"Doğrulama ({len(issues)})")
        if placeholder:
            self.statusBar().showMessage(
                f"Dikkat: {placeholder} yer tutucu uyuşmazlığı var", 6000
            )

    def _jump_to(self, ref: KeyRef) -> None:
        if self.key_panel.select_ref(ref):
            self.editor.focus_first_target()

    def show_about(self) -> None:
        QMessageBox.about(
            self,
            f"{APP_NAME} hakkında",
            f"<h3>{APP_NAME} {__version__}</h3>"
            "<p>Flutter/ARB çeviri editörü.</p>"
            "<p>Dosyalar bayt düzeyinde sadık şekilde yazılır: satır sonu, girinti "
            "ve kodlama korunur, böylece dokunulmayan dosyalar git diff'inde "
            "görünmez.</p>"
            "<p style='color:#969aa2'>Kısayollar: Ctrl+S kaydet · Ctrl+F ara · "
            "Ctrl+Enter sonraki çevrilmemiş · Ctrl+E dışa aktar · Ctrl+I içe aktar "
            "· Ctrl+R doğrula</p>",
        )
