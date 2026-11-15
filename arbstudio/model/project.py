"""Bir ARB projesi: klasör taraması, dil tespiti, anahtar tablosu, düzenleme."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, NamedTuple, Optional, Sequence

from .arb_file import ArbFile
from .keyinfo import KeyStatus, key_status

#: Yaygın ISO 639-1 kodları + birkaç 3 harfli. Dil klasörü/eki tespitinde kullanılır.
KNOWN_LANGS = {
    "aa", "ab", "af", "ak", "am", "an", "ar", "as", "av", "ay", "az", "ba", "be",
    "bg", "bh", "bi", "bm", "bn", "bo", "br", "bs", "ca", "ce", "ch", "co", "cr",
    "cs", "cu", "cv", "cy", "da", "de", "dv", "dz", "ee", "el", "en", "eo", "es",
    "et", "eu", "fa", "ff", "fi", "fj", "fo", "fr", "fy", "ga", "gd", "gl", "gn",
    "gu", "gv", "ha", "he", "hi", "ho", "hr", "ht", "hu", "hy", "hz", "ia", "id",
    "ie", "ig", "ii", "ik", "io", "is", "it", "iu", "ja", "jv", "ka", "kg", "ki",
    "kj", "kk", "kl", "km", "kn", "ko", "kr", "ks", "ku", "kv", "kw", "ky", "la",
    "lb", "lg", "li", "ln", "lo", "lt", "lu", "lv", "mg", "mh", "mi", "mk", "ml",
    "mn", "mr", "ms", "mt", "my", "na", "nb", "nd", "ne", "ng", "nl", "nn", "no",
    "nr", "nv", "ny", "oc", "oj", "om", "or", "os", "pa", "pi", "pl", "ps", "pt",
    "qu", "rm", "rn", "ro", "ru", "rw", "sa", "sc", "sd", "se", "sg", "si", "sk",
    "sl", "sm", "sn", "so", "sq", "sr", "ss", "st", "su", "sv", "sw", "ta", "te",
    "tg", "th", "ti", "tk", "tl", "tn", "to", "tr", "ts", "tt", "tw", "ty", "ug",
    "uk", "ur", "uz", "ve", "vi", "vo", "wa", "wo", "xh", "yi", "yo", "za", "zh",
    "zu", "fil", "ceb", "haw", "hmn", "nso", "ckb",
}

_LANG_TAG_RE = re.compile(
    r"^(?P<base>[A-Za-z]{2,3})(?:[_-](?P<script>[A-Za-z]{4}))?"
    r"(?:[_-](?P<region>[A-Za-z]{2}|\d{3}))?$"
)
_FILE_SUFFIX_RE = re.compile(r"^(?P<stem>.+?)[_-](?P<tag>[A-Za-z]{2,3}(?:[_-][A-Za-z0-9]{2,4}){0,2})$")

#: Taramada atlanan klasörler. `.arbstudio-backups` özellikle önemli: içinde
#: gerçek .arb kopyaları var, atlanmazsa yedekler proje verisi sanılır.
SKIP_DIRS = {
    ".git",
    ".dart_tool",
    "build",
    "node_modules",
    ".venv",
    "__pycache__",
    ".arbstudio-backups",
}


def is_lang_tag(text: str) -> bool:
    """`tr`, `en`, `pt_BR`, `zh-Hant` gibi bir dil etiketi mi?"""
    match = _LANG_TAG_RE.match(text)
    return bool(match) and match.group("base").lower() in KNOWN_LANGS


def normalize_lang(text: str) -> str:
    match = _LANG_TAG_RE.match(text)
    if not match:
        return text
    parts = [match.group("base").lower()]
    if match.group("script"):
        parts.append(match.group("script").capitalize())
    if match.group("region"):
        parts.append(match.group("region").upper())
    return "_".join(parts)


class KeyRef(NamedTuple):
    """Anahtar tablosundaki bir satır: hangi paket (dosya adı) + hangi anahtar."""

    bundle: str
    key: str


@dataclass
class BundleStat:
    total: int = 0
    translated: int = 0
    same: int = 0
    missing: int = 0

    @property
    def percent(self) -> float:
        return 100.0 * self.translated / self.total if self.total else 100.0


class Project:
    """Tek bir kök klasör altındaki tüm .arb dosyaları."""

    def __init__(self, root: Path):
        self.root = Path(root)
        #: bundles[dosya_adı][dil] = ArbFile
        self.bundles: Dict[str, Dict[str, ArbFile]] = {}
        self.languages: List[str] = []
        self.source_lang: str = ""
        self._key_order: List[KeyRef] = []
        self.load_errors: List[str] = []

    # ---------------------------------------------------------------- tarama

    @classmethod
    def scan(cls, root: Path | str, source_lang: Optional[str] = None) -> "Project":
        project = cls(Path(root))
        project.reload(source_lang)
        return project

    def reload(self, source_lang: Optional[str] = None) -> None:
        self.bundles.clear()
        self.load_errors.clear()
        langs: set[str] = set()

        for path in sorted(self._iter_arb_paths()):
            detected = self._detect(path)
            if detected is None:
                self.load_errors.append(f"{path}: dil kodu belirlenemedi, atlandı")
                continue
            lang, bundle = detected
            try:
                arb = ArbFile.load(path, lang)
            except Exception as exc:  # bozuk JSON tüm projeyi düşürmemeli
                self.load_errors.append(f"{path}: okunamadı ({exc})")
                continue
            self.bundles.setdefault(bundle, {})[lang] = arb
            langs.add(lang)

        self.languages = sorted(langs)
        if source_lang and source_lang in self.languages:
            self.source_lang = source_lang
        elif self.source_lang in self.languages:
            pass
        else:
            self.source_lang = self._guess_source_lang()
        self.rebuild_key_order()

    def _iter_arb_paths(self) -> Iterable[Path]:
        for path in self.root.rglob("*.arb"):
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            yield path

    def _detect(self, path: Path) -> Optional[tuple[str, str]]:
        """(dil, paket_adı) tespiti — klasör → dosya eki → @@locale sırasıyla."""
        parent = path.parent.name
        if path.parent != self.root and is_lang_tag(parent):
            return normalize_lang(parent), path.name

        match = _FILE_SUFFIX_RE.match(path.stem)
        if match and is_lang_tag(match.group("tag")):
            return normalize_lang(match.group("tag")), f"{match.group('stem')}.arb"

        locale = ArbFile.peek_locale(path)
        if locale and is_lang_tag(locale):
            return normalize_lang(locale), path.name

        return None

    def _guess_source_lang(self) -> str:
        if not self.languages:
            return ""
        counts = {
            lang: sum(len(files[lang]) for files in self.bundles.values() if lang in files)
            for lang in self.languages
        }
        return max(self.languages, key=lambda lang: (counts[lang], lang == "en", lang))

    # --------------------------------------------------------- anahtar tablosu

    def rebuild_key_order(self) -> None:
        order: List[KeyRef] = []
        for bundle in sorted(self.bundles):
            files = self.bundles[bundle]
            seen: set[str] = set()
            source = files.get(self.source_lang)
            if source is not None:
                for key in source.keys():
                    order.append(KeyRef(bundle, key))
                    seen.add(key)
            # Kaynakta olmayan ama başka dilde bulunan anahtarlar (öksüz) sona eklenir.
            for lang in self.languages:
                arb = files.get(lang)
                if arb is None or lang == self.source_lang:
                    continue
                for key in arb.keys():
                    if key not in seen:
                        order.append(KeyRef(bundle, key))
                        seen.add(key)
        self._key_order = order

    @property
    def key_order(self) -> Sequence[KeyRef]:
        return self._key_order

    def keys_of(self, bundle: str) -> List[KeyRef]:
        return [ref for ref in self._key_order if ref.bundle == bundle]

    # ---------------------------------------------------------------- erişim

    def file(self, bundle: str, lang: str) -> Optional[ArbFile]:
        return self.bundles.get(bundle, {}).get(lang)

    def value(self, ref: KeyRef, lang: str) -> Optional[str]:
        arb = self.file(ref.bundle, lang)
        if arb is None:
            return None
        return arb.entries.get(ref.key)

    def source_value(self, ref: KeyRef) -> str:
        return self.value(ref, self.source_lang) or ""

    def status(self, ref: KeyRef, lang: str) -> KeyStatus:
        return key_status(self.source_value(ref), self.value(ref, lang))

    def worst_status(self, ref: KeyRef, langs: Optional[Sequence[str]] = None) -> KeyStatus:
        """Hedef diller arasındaki en kötü durum — liste rozetinde gösterilir."""
        targets = langs if langs is not None else [
            lang for lang in self.languages if lang != self.source_lang
        ]
        worst = KeyStatus.TRANSLATED
        for lang in targets:
            status = self.status(ref, lang)
            if status is KeyStatus.MISSING:
                return KeyStatus.MISSING
            if status is KeyStatus.SAME_AS_SOURCE:
                worst = KeyStatus.SAME_AS_SOURCE
        return worst

    # -------------------------------------------------------------- düzenleme

    def set_value(self, ref: KeyRef, lang: str, value: str) -> bool:
        arb = self.file(ref.bundle, lang)
        if arb is None:
            arb = self._create_bundle_file(ref.bundle, lang)
        return arb.set(ref.key, value)

    def add_key(self, bundle: str, key: str, source_value: str = "") -> KeyRef:
        if bundle not in self.bundles:
            raise KeyError(f"Bilinmeyen paket: {bundle}")
        if any(ref.bundle == bundle and ref.key == key for ref in self._key_order):
            raise ValueError(f"'{key}' anahtarı {bundle} içinde zaten var")
        for lang in self.languages:
            arb = self.file(bundle, lang) or self._create_bundle_file(bundle, lang)
            arb.set(key, source_value if lang == self.source_lang else "")
        self.rebuild_key_order()
        return KeyRef(bundle, key)

    def rename_key(self, ref: KeyRef, new_key: str) -> KeyRef:
        if new_key == ref.key:
            return ref
        for lang in self.languages:
            arb = self.file(ref.bundle, lang)
            if arb is not None:
                arb.rename(ref.key, new_key)
        self.rebuild_key_order()
        return KeyRef(ref.bundle, new_key)

    def delete_key(self, ref: KeyRef) -> int:
        removed = 0
        for lang in self.languages:
            arb = self.file(ref.bundle, lang)
            if arb is not None and arb.remove(ref.key):
                removed += 1
        self.rebuild_key_order()
        return removed

    def move_key(self, ref: KeyRef, target_bundle: str) -> KeyRef:
        if target_bundle == ref.bundle:
            return ref
        if target_bundle not in self.bundles:
            raise KeyError(f"Bilinmeyen paket: {target_bundle}")
        for lang in self.languages:
            src = self.file(ref.bundle, lang)
            if src is None or ref.key not in src.entries:
                continue
            dst = self.file(target_bundle, lang) or self._create_bundle_file(
                target_bundle, lang
            )
            dst.set(ref.key, src.entries[ref.key])
            src.remove(ref.key)
        self.rebuild_key_order()
        return KeyRef(target_bundle, ref.key)

    def add_language(self, lang: str, copy_values: bool = False) -> List[Path]:
        """Kaynak dilin tüm paketlerini yeni dil için oluşturur (değerler boş)."""
        lang = normalize_lang(lang)
        if lang in self.languages:
            raise ValueError(f"'{lang}' dili zaten var")
        created: List[Path] = []
        for bundle in sorted(self.bundles):
            source = self.file(bundle, self.source_lang)
            if source is None:
                continue
            arb = self._create_bundle_file(bundle, lang, template=source)
            for key, value in source.entries.items():
                arb.entries[key] = value if copy_values else ""
            arb.dirty = True
            created.append(arb.path)
        self.languages = sorted(set(self.languages) | {lang})
        self.rebuild_key_order()
        return created

    def _create_bundle_file(
        self, bundle: str, lang: str, template: Optional[ArbFile] = None
    ) -> ArbFile:
        if template is None:
            template = self.file(bundle, self.source_lang)
        if template is not None:
            path = self._sibling_path(template, lang, bundle)
            style = template.style
        else:
            path = self.root / lang / bundle
            from .arb_file import FileStyle

            style = FileStyle()
        arb = ArbFile(path=path, lang=lang, style=style)
        arb.set_locale(lang)
        arb.dirty = True
        self.bundles.setdefault(bundle, {})[lang] = arb
        return arb

    @staticmethod
    def _sibling_path(template: ArbFile, lang: str, bundle: str) -> Path:
        """Şablon dosyanın düzenine göre yeni dil için yol üretir."""
        if is_lang_tag(template.path.parent.name):
            return template.path.parent.parent / lang / bundle
        stem = Path(bundle).stem
        match = _FILE_SUFFIX_RE.match(template.path.stem)
        if match and is_lang_tag(match.group("tag")):
            return template.path.parent / f"{stem}_{lang}.arb"
        return template.path.parent / lang / bundle

    # ---------------------------------------------------------------- kayıt

    @property
    def dirty_files(self) -> List[ArbFile]:
        return [
            arb
            for files in self.bundles.values()
            for arb in files.values()
            if arb.dirty
        ]

    @property
    def is_dirty(self) -> bool:
        return bool(self.dirty_files)

    #: Yedeklerin toplandığı klasör — tek satırla .gitignore'a eklenebilsin diye.
    BACKUP_DIRNAME = ".arbstudio-backups"

    @property
    def backup_dir(self) -> Path:
        return self.root / self.BACKUP_DIRNAME

    def save_all(self, backup: bool = True) -> List[Path]:
        saved: List[Path] = []
        for arb in self.dirty_files:
            arb.save(backup=backup, backup_dir=self.backup_dir if backup else None)
            saved.append(arb.path)
        return saved

    # ------------------------------------------------------------ istatistik

    def stats(self, lang: str) -> Dict[str, BundleStat]:
        """Paket adı → istatistik. `__total__` anahtarı genel toplamı taşır."""
        result: Dict[str, BundleStat] = {}
        total = BundleStat()
        for bundle in sorted(self.bundles):
            stat = BundleStat()
            for ref in self.keys_of(bundle):
                stat.total += 1
                status = self.status(ref, lang)
                if status is KeyStatus.TRANSLATED:
                    stat.translated += 1
                elif status is KeyStatus.SAME_AS_SOURCE:
                    stat.same += 1
                else:
                    stat.missing += 1
            result[bundle] = stat
            total.total += stat.total
            total.translated += stat.translated
            total.same += stat.same
            total.missing += stat.missing
        result["__total__"] = total
        return result

    @property
    def key_count(self) -> int:
        return len(self._key_order)
