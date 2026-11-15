"""Çevrilmiş TXT'yi geri yükleme: format algılama, hizalama denetimi, önizleme.

Hiçbir şey doğrudan yazılmaz — `build_import_plan()` yalnızca bir plan üretir.
Uyarılar ve satır satır önizleme kullanıcıya gösterildikten sonra `apply()`
çağrılır.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from ..model.keyinfo import placeholders
from ..model.project import KeyRef, Project
from .escaping import unescape_value
from .txt_export import ExportFormat, manifest_path_for

_TSV_LINE_RE = re.compile(r"^(?P<key>[A-Za-z_][A-Za-z0-9_.\-]*)\t(?P<value>.*)$")


class ImportAction(str, Enum):
    NEW = "new"                    # hedefte boştu, değer geliyor
    CHANGED = "changed"            # mevcut değer değişiyor
    UNCHANGED = "unchanged"        # aynı, yazılmayacak
    SKIPPED_EMPTY = "skipped"      # TXT satırı boş, mevcut çeviri korunuyor
    UNKNOWN_KEY = "unknown"        # TSV'de projede olmayan anahtar

    @property
    def label(self) -> str:
        return {
            ImportAction.NEW: "yeni",
            ImportAction.CHANGED: "değişti",
            ImportAction.UNCHANGED: "aynı",
            ImportAction.SKIPPED_EMPTY: "boş — atlandı",
            ImportAction.UNKNOWN_KEY: "bilinmeyen anahtar",
        }[self]


@dataclass
class ImportRow:
    line_no: int
    ref: Optional[KeyRef]
    source: str
    current: str
    new: str
    action: ImportAction
    raw_key: str = ""
    #: Kaynakta olup yeni değerde bulunmayan / fazladan olan yer tutucular.
    placeholder_issue: str = ""


@dataclass
class Divergence:
    line_no: int
    key: str
    source: str
    imported: str
    reason: str


@dataclass
class ImportPlan:
    fmt: ExportFormat
    target_lang: str
    rows: List[ImportRow] = field(default_factory=list)
    line_count: int = 0
    expected_count: int = 0
    divergence: Optional[Divergence] = None
    suspicious_count: int = 0
    unknown_keys: List[str] = field(default_factory=list)
    untouched_keys: List[KeyRef] = field(default_factory=list)
    manifest_used: bool = False
    warnings: List[str] = field(default_factory=list)

    @property
    def count_mismatch(self) -> bool:
        return self.line_count != self.expected_count

    @property
    def writable_rows(self) -> List[ImportRow]:
        return [
            row
            for row in self.rows
            if row.action in (ImportAction.NEW, ImportAction.CHANGED)
        ]

    @property
    def is_risky(self) -> bool:
        """Yazmadan önce kullanıcıyı açıkça uyarmayı gerektiren durum.

        TSV'de eşleşme anahtarla yapıldığı için satır sayısı farkı tehlikeli
        değil — yalnızca bazı anahtarların dokunulmadığı anlamına gelir.
        """
        if self.unknown_keys:
            return True
        if self.fmt is ExportFormat.LINES and self.count_mismatch:
            return True
        threshold = max(3, self.expected_count // 100)
        return self.suspicious_count > threshold

    def counts(self) -> Dict[ImportAction, int]:
        result = {action: 0 for action in ImportAction}
        for row in self.rows:
            result[row.action] += 1
        return result

    def apply(self, project: Project) -> int:
        written = 0
        for row in self.writable_rows:
            if row.ref is None:
                continue
            if project.set_value(row.ref, self.target_lang, row.new):
                written += 1
        return written


# --------------------------------------------------------------------- okuma


def read_lines(path: Path | str) -> List[str]:
    """TXT'yi okur; BOM ve satır sonu farkları şeffaf biçimde soyulur."""
    text = Path(path).read_text(encoding="utf-8-sig")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    # Dosya sonundaki tek newline yapay bir boş satır üretir.
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def load_manifest(txt_path: Path | str) -> Optional[dict]:
    path = manifest_path_for(Path(txt_path))
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def detect_format(lines: Sequence[str], known_keys: Optional[set[str]] = None) -> ExportFormat:
    """İlk dolu satırlara bakarak TSV mi satır bazlı mı olduğunu belirler.

    Birincil sinyal biçim: `anahtar<TAB>değer`. Satır bazlı dışa aktarımda
    sekmeler `\\t` olarak kaçırıldığı için gerçek bir TAB karakteri oraya
    giremez. Tanınan anahtar sayısı yalnızca doğrulama amaçlı kullanılır —
    aksi hâlde tamamı yeni anahtarlardan oluşan küçük bir TSV yanlış algılanır.
    """
    sample = [line for line in lines if line.strip()][:60]
    if not sample:
        return ExportFormat.LINES

    shaped = [m for m in (_TSV_LINE_RE.match(line) for line in sample) if m]
    if len(shaped) < len(sample) * 0.6:
        return ExportFormat.LINES
    if known_keys is None:
        return ExportFormat.TSV
    # En az bir anahtar projede tanınıyorsa TSV say; hiçbiri tanınmıyorsa
    # muhtemelen içinde sekme geçen serbest metindir.
    return (
        ExportFormat.TSV
        if any(m.group("key") in known_keys for m in shaped)
        else ExportFormat.LINES
    )


# ------------------------------------------------------------------ hizalama


def _refs_from_manifest(project: Project, manifest: dict) -> Optional[List[KeyRef]]:
    entries = manifest.get("entries")
    if not isinstance(entries, list):
        return None
    refs: List[KeyRef] = []
    for entry in entries:
        if not isinstance(entry, dict):
            return None
        bundle, key = entry.get("file"), entry.get("key")
        if not isinstance(bundle, str) or not isinstance(key, str):
            return None
        refs.append(KeyRef(bundle, key))
    return refs


def _scan_divergence(
    project: Project,
    refs: Sequence[KeyRef],
    values: Sequence[str],
    manifest: Optional[dict],
) -> tuple[Optional[Divergence], int]:
    """Yer tutucu parmak izi ile hizalama sapmasını arar.

    Doğru çevrilmiş bir satır `{count}` gibi yer tutucuları korur; kayma olduğunda
    yer tutucu kümeleri tutmaz olur.

    Dönen satır numarası sapmanın **tespit edilebildiği ilk** satırdır, kaymanın
    başladığı satır değil: yalnızca yer tutucu içeren anahtarlar sinyal üretir,
    dolayısıyla gerçek kayma birkaç satır daha erken başlamış olabilir. Kesin
    uyarı sinyali satır sayısı farkıdır; bu tarama nereye bakılacağını söyler.
    """
    manifest_entries = manifest.get("entries") if manifest else None
    first: Optional[Divergence] = None
    suspicious = 0

    for index in range(min(len(refs), len(values))):
        ref = refs[index]
        if isinstance(manifest_entries, list) and index < len(manifest_entries):
            entry = manifest_entries[index]
            expected = set(entry.get("ph", [])) if isinstance(entry, dict) else set()
        else:
            expected = placeholders(project.source_value(ref))
        if not expected:
            continue
        actual = placeholders(values[index])
        if actual == expected:
            continue
        suspicious += 1
        if first is None:
            first = Divergence(
                line_no=index + 1,
                key=ref.key,
                source=project.source_value(ref),
                imported=values[index],
                reason=(
                    "Yer tutucu uyuşmuyor — beklenen {%s}, gelen {%s}"
                    % (", ".join(sorted(expected)) or "-", ", ".join(sorted(actual)) or "-")
                ),
            )
    return first, suspicious


def build_import_plan(
    project: Project,
    target_lang: str,
    txt_path: Path | str,
    scope_refs: Optional[Sequence[KeyRef]] = None,
    fmt: Optional[ExportFormat] = None,
    write_empty: bool = False,
    use_manifest: bool = True,
) -> ImportPlan:
    """TXT'yi okuyup uygulanabilir bir plan üretir. Projeye dokunmaz."""
    txt_path = Path(txt_path)
    lines = read_lines(txt_path)
    manifest = load_manifest(txt_path) if use_manifest else None

    known_keys = {ref.key for ref in project.key_order}
    if fmt is None:
        fmt = detect_format(lines, known_keys)
        if manifest and manifest.get("format") in (f.value for f in ExportFormat):
            fmt = ExportFormat(manifest["format"])

    plan = ImportPlan(fmt=fmt, target_lang=target_lang, line_count=len(lines))

    if manifest:
        root = manifest.get("root")
        if root and Path(root) != project.root:
            plan.warnings.append(
                f"Manifest başka bir kök klasör için üretilmiş: {root}"
            )

    if fmt is ExportFormat.TSV:
        _build_tsv_plan(project, plan, lines, scope_refs, write_empty)
    else:
        _build_lines_plan(project, plan, lines, scope_refs, manifest, write_empty)

    return plan


def _resolve_ref(project: Project, key: str, scope: Optional[set[str]]) -> Optional[KeyRef]:
    matches = [ref for ref in project.key_order if ref.key == key]
    if not matches:
        return None
    if scope:
        scoped = [ref for ref in matches if ref.bundle in scope]
        if scoped:
            return scoped[0]
    return matches[0]


def _build_tsv_plan(
    project: Project,
    plan: ImportPlan,
    lines: Sequence[str],
    scope_refs: Optional[Sequence[KeyRef]],
    write_empty: bool,
) -> None:
    scope_bundles = {ref.bundle for ref in scope_refs} if scope_refs else None
    expected_refs = list(scope_refs) if scope_refs else list(project.key_order)
    plan.expected_count = len(expected_refs)
    seen: set[KeyRef] = set()

    for index, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        match = _TSV_LINE_RE.match(line)
        if not match:
            plan.rows.append(
                ImportRow(
                    line_no=index,
                    ref=None,
                    source="",
                    current="",
                    new=line,
                    action=ImportAction.UNKNOWN_KEY,
                    raw_key="(TAB bulunamadı)",
                )
            )
            plan.unknown_keys.append(f"satır {index}: TAB ayırıcı yok")
            continue

        key = match.group("key")
        value = unescape_value(match.group("value"))
        ref = _resolve_ref(project, key, scope_bundles)
        if ref is None:
            plan.rows.append(
                ImportRow(
                    line_no=index,
                    ref=None,
                    source="",
                    current="",
                    new=value,
                    action=ImportAction.UNKNOWN_KEY,
                    raw_key=key,
                )
            )
            plan.unknown_keys.append(key)
            continue

        seen.add(ref)
        plan.rows.append(_make_row(project, plan, index, ref, value, write_empty, key))

    plan.untouched_keys = [ref for ref in expected_refs if ref not in seen]
    # TSV'de satır sırası önemsiz (eşleşme anahtarla yapılır), bu yüzden hizalama
    # sapması diye bir şey yok; yalnızca yer tutucu ihlalleri sayılır.
    matched = [(row.ref, row.new) for row in plan.rows if row.ref is not None]
    _, plan.suspicious_count = _scan_divergence(
        project, [ref for ref, _ in matched], [value for _, value in matched], None
    )
    plan.line_count = sum(1 for line in lines if line.strip())


def _build_lines_plan(
    project: Project,
    plan: ImportPlan,
    lines: Sequence[str],
    scope_refs: Optional[Sequence[KeyRef]],
    manifest: Optional[dict],
    write_empty: bool,
) -> None:
    refs: Optional[List[KeyRef]] = None
    if manifest:
        refs = _refs_from_manifest(project, manifest)
        if refs is not None:
            plan.manifest_used = True
            missing = [
                ref
                for ref in refs
                if project.file(ref.bundle, project.source_lang) is None
            ]
            if missing:
                plan.warnings.append(
                    f"Manifestteki {len(missing)} girdinin paketi projede yok."
                )
    if refs is None:
        refs = list(scope_refs) if scope_refs else list(project.key_order)

    plan.expected_count = len(refs)
    values = [unescape_value(line) for line in lines]
    plan.divergence, plan.suspicious_count = _scan_divergence(
        project, refs, values, manifest
    )

    for index in range(min(len(refs), len(values))):
        plan.rows.append(
            _make_row(project, plan, index + 1, refs[index], values[index], write_empty)
        )

    if len(values) > len(refs):
        for index in range(len(refs), len(values)):
            plan.rows.append(
                ImportRow(
                    line_no=index + 1,
                    ref=None,
                    source="",
                    current="",
                    new=values[index],
                    action=ImportAction.UNKNOWN_KEY,
                    raw_key="(fazla satır)",
                )
            )
    elif len(refs) > len(values):
        plan.untouched_keys = list(refs[len(values):])


def _make_row(
    project: Project,
    plan: ImportPlan,
    line_no: int,
    ref: KeyRef,
    value: str,
    write_empty: bool,
    raw_key: str = "",
) -> ImportRow:
    source = project.source_value(ref)
    current = project.value(ref, plan.target_lang) or ""

    if not value and not write_empty:
        action = ImportAction.SKIPPED_EMPTY
    elif value == current:
        action = ImportAction.UNCHANGED
    elif not current:
        action = ImportAction.NEW
    else:
        action = ImportAction.CHANGED

    issue = ""
    if value:
        expected, actual = placeholders(source), placeholders(value)
        if expected != actual:
            missing = sorted(expected - actual)
            extra = sorted(actual - expected)
            parts = []
            if missing:
                parts.append("eksik: " + ", ".join("{%s}" % name for name in missing))
            if extra:
                parts.append("fazla: " + ", ".join("{%s}" % name for name in extra))
            issue = "; ".join(parts)

    return ImportRow(
        line_no=line_no,
        ref=ref,
        source=source,
        current=current,
        new=value,
        action=action,
        raw_key=raw_key or ref.key,
        placeholder_issue=issue,
    )
