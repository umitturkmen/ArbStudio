"""Bir dilin metinlerini TXT olarak dışa aktarma + yanına eşleme manifesti."""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import List, Optional, Sequence

from ..model.keyinfo import placeholders
from ..model.project import KeyRef, Project
from .escaping import escape_value

MANIFEST_SUFFIX = ".arbmap.json"
MANIFEST_VERSION = 1


class ExportFormat(str, Enum):
    #: Satır N = anahtar N. Toplu çeviri araçlarına yapıştırmak için.
    LINES = "lines"
    #: `anahtar<TAB>değer`. Sıra bozulsa bile anahtarla eşleşir.
    TSV = "tsv"

    @property
    def label(self) -> str:
        return {
            ExportFormat.LINES: "Satır bazlı (satır N = anahtar N)",
            ExportFormat.TSV: "Anahtar + TAB + değer",
        }[self]


@dataclass
class ExportResult:
    txt_path: Path
    manifest_path: Optional[Path]
    line_count: int
    empty_count: int


def manifest_path_for(txt_path: Path) -> Path:
    return txt_path.with_suffix("").with_name(txt_path.stem + MANIFEST_SUFFIX)


def build_text(
    project: Project,
    lang: str,
    refs: Sequence[KeyRef],
    fmt: ExportFormat,
) -> tuple[str, int]:
    lines: List[str] = []
    empty = 0
    for ref in refs:
        value = project.value(ref, lang) or ""
        if not value:
            empty += 1
        escaped = escape_value(value)
        if fmt is ExportFormat.TSV:
            lines.append(f"{ref.key}\t{escaped}")
        else:
            lines.append(escaped)
    return "\n".join(lines) + "\n", empty


def build_manifest(
    project: Project,
    lang: str,
    refs: Sequence[KeyRef],
    fmt: ExportFormat,
) -> dict:
    entries = []
    for ref in refs:
        source = project.source_value(ref)
        entry: dict[str, object] = {"file": ref.bundle, "key": ref.key}
        names = sorted(placeholders(source))
        if names:
            # Hizalama sapmasını yakalamak için parmak izi.
            entry["ph"] = names
        if not source:
            entry["empty"] = True
        entries.append(entry)

    joined = "\n".join(project.source_value(ref) for ref in refs)
    return {
        "version": MANIFEST_VERSION,
        "generator": "ARB Studio",
        "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "format": fmt.value,
        "root": str(project.root),
        "source_lang": project.source_lang,
        "exported_lang": lang,
        "line_count": len(refs),
        "source_sha256": hashlib.sha256(joined.encode("utf-8")).hexdigest(),
        "entries": entries,
    }


def export_txt(
    project: Project,
    lang: str,
    refs: Sequence[KeyRef],
    txt_path: Path | str,
    fmt: ExportFormat = ExportFormat.LINES,
    write_manifest: bool = True,
) -> ExportResult:
    txt_path = Path(txt_path)
    txt_path.parent.mkdir(parents=True, exist_ok=True)

    text, empty = build_text(project, lang, refs, fmt)
    # UTF-8 BOM: Excel ve Not Defteri'nin Türkçe/Arapça karakterleri doğru
    # açması için. Okuma tarafında utf-8-sig ile şeffaf biçimde soyulur.
    txt_path.write_text(text, encoding="utf-8-sig", newline="\r\n")

    manifest_file: Optional[Path] = None
    if write_manifest:
        manifest_file = manifest_path_for(txt_path)
        manifest_file.write_text(
            json.dumps(build_manifest(project, lang, refs, fmt), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    return ExportResult(
        txt_path=txt_path,
        manifest_path=manifest_file,
        line_count=len(refs),
        empty_count=empty,
    )
