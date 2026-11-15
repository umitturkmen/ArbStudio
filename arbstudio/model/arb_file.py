"""Tek bir .arb dosyasının okunması/yazılması.

Tasarım kuralı: dokunulmamış bir dosya yeniden yazıldığında **baytları birebir
aynı** kalmalı. Aksi hâlde 3000 anahtarlık bir projede satır sonu veya girinti
farkı yüzünden sahte git diff'leri oluşur. Bu yüzden dosyanın biçim özellikleri
(satır sonu, girinti, BOM, sondaki newline, ASCII kaçışı) okurken tespit edilip
yazarken geri uygulanır.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterator, Optional

LOCALE_KEY = "@@locale"


@dataclass
class FileStyle:
    """Bir .arb dosyasının bayt düzeyi biçim özellikleri."""

    newline: str = "\n"
    indent: int = 2
    bom: bool = False
    trailing_newline: bool = True
    ensure_ascii: bool = False

    @classmethod
    def detect(cls, raw: bytes) -> "FileStyle":
        bom = raw.startswith(b"\xef\xbb\xbf")
        body = raw[3:] if bom else raw
        newline = "\r\n" if b"\r\n" in body else "\n"
        text = body.decode("utf-8")

        indent = 2
        for line in text.splitlines()[1:]:
            stripped = line.lstrip(" ")
            if stripped and stripped != line:
                indent = len(line) - len(stripped)
                break

        # ASCII kaçışı: gövdede ASCII dışı bayt yoksa ve \uXXXX dizisi varsa.
        ensure_ascii = bool(re.search(r"\\u[0-9a-fA-F]{4}", text)) and all(
            ord(ch) < 128 for ch in text
        )

        return cls(
            newline=newline,
            indent=indent,
            bom=bom,
            trailing_newline=text.endswith("\n"),
            ensure_ascii=ensure_ascii,
        )


@dataclass
class ArbFile:
    """Bellekteki bir .arb dosyası. Anahtar sırası korunur."""

    path: Path
    lang: str
    entries: Dict[str, str] = field(default_factory=dict)
    style: FileStyle = field(default_factory=FileStyle)
    #: `@@locale` dışındaki `@`-önekli girdiler (ARB metadata). Olduğu gibi korunur.
    meta: Dict[str, object] = field(default_factory=dict)
    dirty: bool = False

    # ---------------------------------------------------------------- okuma

    @classmethod
    def load(cls, path: os.PathLike | str, lang: str) -> "ArbFile":
        path = Path(path)
        raw = path.read_bytes()
        style = FileStyle.detect(raw)
        text = raw.decode("utf-8-sig")
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError(f"{path}: ARB kök öğesi bir JSON nesnesi olmalı")

        entries: Dict[str, str] = {}
        meta: Dict[str, object] = {}
        for key, value in data.items():
            if key == LOCALE_KEY:
                meta[key] = value
                continue
            if key.startswith("@"):
                meta[key] = value
                continue
            entries[key] = value if isinstance(value, str) else json.dumps(value)

        return cls(path=path, lang=lang, entries=entries, style=style, meta=meta)

    @classmethod
    def peek_locale(cls, path: os.PathLike | str) -> Optional[str]:
        """Dosyayı tam ayrıştırmadan `@@locale` değerini okumayı dener."""
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return None
        value = data.get(LOCALE_KEY) if isinstance(data, dict) else None
        return value if isinstance(value, str) and value else None

    # ---------------------------------------------------------------- yazma

    def serialize(self) -> bytes:
        payload: Dict[str, object] = {}
        if LOCALE_KEY in self.meta:
            payload[LOCALE_KEY] = self.meta[LOCALE_KEY]
        payload.update(self.entries)
        for key, value in self.meta.items():
            if key != LOCALE_KEY:
                payload[key] = value

        text = json.dumps(
            payload,
            indent=self.style.indent,
            ensure_ascii=self.style.ensure_ascii,
        )
        if self.style.trailing_newline:
            text += "\n"
        if self.style.newline != "\n":
            text = text.replace("\n", self.style.newline)
        data = text.encode("utf-8")
        if self.style.bom:
            data = b"\xef\xbb\xbf" + data
        return data

    def save(self, backup: bool = True, backup_dir: Optional[Path] = None) -> None:
        """Dosyayı yazar. Yedek, verilmişse `backup_dir` altına aynı göreli
        yolla kopyalanır — yan yana `.bak` bırakmak sürüm kontrolünü kirletir."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if backup and self.path.exists():
            shutil.copy2(self.path, self._backup_path(backup_dir))
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_bytes(self.serialize())
        os.replace(tmp, self.path)
        self.dirty = False

    def _backup_path(self, backup_dir: Optional[Path]) -> Path:
        if backup_dir is not None:
            try:
                relative = self.path.relative_to(backup_dir.parent)
            except ValueError:
                relative = Path(self.path.name)
            target = backup_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            return target
        return self.path.with_suffix(self.path.suffix + ".bak")

    # -------------------------------------------------------------- yardımcı

    @property
    def name(self) -> str:
        """Paket adı — aynı ada sahip dosyalar diller arasında eşleşir."""
        return self.path.name

    @property
    def locale(self) -> Optional[str]:
        value = self.meta.get(LOCALE_KEY)
        return value if isinstance(value, str) else None

    def set_locale(self, lang: str) -> None:
        self.meta[LOCALE_KEY] = lang

    def get(self, key: str, default: str = "") -> str:
        return self.entries.get(key, default)

    def set(self, key: str, value: str) -> bool:
        """Değeri yazar; gerçekten değiştiyse True döner."""
        if self.entries.get(key) == value:
            return False
        self.entries[key] = value
        self.dirty = True
        return True

    def remove(self, key: str) -> bool:
        if key in self.entries:
            del self.entries[key]
            self.meta.pop(f"@{key}", None)
            self.dirty = True
            return True
        return False

    def rename(self, old: str, new: str) -> bool:
        """Anahtarı sırasını bozmadan yeniden adlandırır."""
        if old not in self.entries or old == new:
            return False
        self.entries = {
            (new if k == old else k): v for k, v in self.entries.items()
        }
        if f"@{old}" in self.meta:
            self.meta[f"@{new}"] = self.meta.pop(f"@{old}")
        self.dirty = True
        return True

    def keys(self) -> Iterator[str]:
        return iter(self.entries)

    def __len__(self) -> int:
        return len(self.entries)
