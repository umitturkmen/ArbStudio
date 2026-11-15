"""Küçük diyaloglar: yeni dil, anahtar ekle/taşı, API ayarları."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QSpinBox,
    QVBoxLayout,
)

from ...model.project import KeyRef, Project, is_lang_tag, normalize_lang
from ...services.translator import (
    AVAILABLE_MODELS,
    DEFAULT_BATCH_SIZE,
    DEFAULT_MODEL,
    ENV_KEY,
)

FLUTTER_REMINDER = """Yeni dil dosyaları oluşturuldu. Flutter tarafında yapılacaklar:

1. lib/l10n/l10n.dart  →  supportedLanguages listesine '{code}' ekle
2. pubspec.yaml  →  assets bölümüne assets/translations/{code}/ ekle
3. Android: android/app/src/main/res/values-{code}/strings.xml
   + res/xml/locales_config.xml içine locale satırı
4. iOS: ios/Runner/{code}.lproj/InfoPlist.strings
   + Info.plist CFBundleLocalizations + Xcode knownRegions
5. RTL dilse (ar, fa, ur): layout'ları EdgeInsetsDirectional denetiminden geçir
6. Doğrula: dart test test/l10n_test.dart

ARB Studio bu dosyalara dokunmaz — yalnızca .arb dosyalarını yönetir."""


class NewLanguageDialog(QDialog):
    def __init__(self, project: Project, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Yeni dil ekle")
        self.setMinimumWidth(440)
        self.project = project
        self.created_lang: Optional[str] = None

        self.code_edit = QLineEdit()
        self.code_edit.setPlaceholderText("ör. ar, de, fr, pt_BR")

        self.copy_check = QCheckBox(
            "Değerleri kaynak dilden kopyala (boş bırakmak yerine)"
        )

        info = QLabel(
            f"Kaynak dilin ({project.source_lang}) tüm {len(project.bundles)} .arb "
            f"dosyası, {project.key_count} anahtarla birlikte yeni dil için "
            "oluşturulur. Dosyalar Kaydet dediğinizde diske yazılır."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #969aa2;")

        form = QFormLayout()
        form.addRow("Dil kodu:", self.code_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Oluştur")
        buttons.accepted.connect(self._create)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.copy_check)
        layout.addWidget(info)
        layout.addSpacing(4)
        layout.addWidget(buttons)

    def _create(self) -> None:
        code = self.code_edit.text().strip()
        if not code:
            return
        if not is_lang_tag(code):
            answer = QMessageBox.question(
                self,
                "Tanınmayan dil kodu",
                f"'{code}' bilinen bir ISO dil kodu değil. Yine de oluşturulsun mu?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
        try:
            created = self.project.add_language(code, self.copy_check.isChecked())
        except ValueError as exc:
            QMessageBox.warning(self, "Oluşturulamadı", str(exc))
            return

        self.created_lang = normalize_lang(code)
        QMessageBox.information(
            self,
            "Dil eklendi",
            f"{len(created)} dosya oluşturuldu.\n\n"
            + FLUTTER_REMINDER.format(code=self.created_lang),
        )
        self.accept()


class AddKeyDialog(QDialog):
    def __init__(self, project: Project, default_bundle: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Anahtar ekle")
        self.setMinimumWidth(500)
        self.project = project
        self.created: Optional[KeyRef] = None

        self.bundle_box = QComboBox()
        for bundle in sorted(project.bundles):
            self.bundle_box.addItem(bundle, bundle)
        if default_bundle:
            index = self.bundle_box.findData(default_bundle)
            if index >= 0:
                self.bundle_box.setCurrentIndex(index)

        self.key_edit = QLineEdit()
        self.key_edit.setPlaceholderText("alan_slug  (ör. zakat_nisap_error)")

        self.value_edit = QPlainTextEdit()
        self.value_edit.setFixedHeight(76)
        self.value_edit.setPlaceholderText(f"{project.source_lang} değeri")

        form = QFormLayout()
        form.addRow("Dosya:", self.bundle_box)
        form.addRow("Anahtar:", self.key_edit)
        form.addRow(f"Değer ({project.source_lang}):", self.value_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Ekle")
        buttons.accepted.connect(self._create)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(
            self._hint("Anahtar tüm dillerde oluşturulur; hedef diller boş kalır.")
        )
        layout.addWidget(buttons)

    @staticmethod
    def _hint(text: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet("color: #969aa2;")
        return label

    def _create(self) -> None:
        key = self.key_edit.text().strip()
        if not key:
            return
        try:
            self.created = self.project.add_key(
                self.bundle_box.currentData(), key, self.value_edit.toPlainText()
            )
        except (KeyError, ValueError) as exc:
            QMessageBox.warning(self, "Eklenemedi", str(exc))
            return
        self.accept()


class MoveKeyDialog(QDialog):
    def __init__(self, project: Project, ref: KeyRef, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Anahtarı başka dosyaya taşı")
        self.setMinimumWidth(420)
        self.project = project
        self.ref = ref
        self.moved: Optional[KeyRef] = None

        self.bundle_box = QComboBox()
        for bundle in sorted(project.bundles):
            if bundle != ref.bundle:
                self.bundle_box.addItem(bundle, bundle)

        form = QFormLayout()
        form.addRow("Anahtar:", QLabel(f"{ref.key}  ({ref.bundle})"))
        form.addRow("Hedef dosya:", self.bundle_box)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Taşı")
        buttons.accepted.connect(self._move)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _move(self) -> None:
        target = self.bundle_box.currentData()
        if not target:
            return
        try:
            self.moved = self.project.move_key(self.ref, target)
        except KeyError as exc:
            QMessageBox.warning(self, "Taşınamadı", str(exc))
            return
        self.accept()


class ApiSettingsDialog(QDialog):
    """Claude API ayarları — anahtar QSettings'te saklanır."""

    def __init__(self, settings: QSettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Çeviri (Claude API) ayarları")
        self.setMinimumWidth(520)
        self.settings = settings

        self.key_edit = QLineEdit(settings.value("api/key", "", str))
        self.key_edit.setEchoMode(QLineEdit.Password)
        self.key_edit.setPlaceholderText("sk-ant-…")

        self.model_box = QComboBox()
        for model_id, label in AVAILABLE_MODELS:
            self.model_box.addItem(label, model_id)
        current = settings.value("api/model", DEFAULT_MODEL, str)
        index = self.model_box.findData(current)
        self.model_box.setCurrentIndex(max(0, index))

        self.batch_spin = QSpinBox()
        self.batch_spin.setRange(5, 100)
        self.batch_spin.setValue(int(settings.value("api/batch", DEFAULT_BATCH_SIZE)))

        form = QFormLayout()
        form.addRow("API anahtarı:", self.key_edit)
        form.addRow("Model:", self.model_box)
        form.addRow("Grup boyutu:", self.batch_spin)

        note = QLabel(
            f"<b>{ENV_KEY}</b> ortam değişkeni tanımlıysa buradaki anahtarın yerine "
            "o kullanılır. Anahtar bu makinedeki kullanıcı ayarlarında saklanır; "
            "şifrelenmez."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #969aa2;")

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addSpacing(4)
        layout.addWidget(buttons)

    def _save(self) -> None:
        self.settings.setValue("api/key", self.key_edit.text().strip())
        self.settings.setValue("api/model", self.model_box.currentData())
        self.settings.setValue("api/batch", self.batch_spin.value())
        self.accept()
