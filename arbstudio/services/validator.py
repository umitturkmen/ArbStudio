"""Çeviri kalite denetimi (QA)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Sequence

from ..model.keyinfo import (
    KeyStatus,
    PLURAL_SUFFIXES,
    has_turkish_chars,
    key_status,
    placeholders,
    plural_group,
)
from ..model.project import KeyRef, Project


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"

    @property
    def label(self) -> str:
        return {"error": "Hata", "warning": "Uyarı", "info": "Bilgi"}[self.value]


class Rule(str, Enum):
    PLACEHOLDER = "placeholder"
    MISSING = "missing"
    SAME_AS_SOURCE = "same_as_source"
    PLURAL = "plural"
    PARITY = "parity"
    CONSISTENCY = "consistency"
    WHITESPACE = "whitespace"
    STRAY_TURKISH = "stray_turkish"

    @property
    def label(self) -> str:
        return {
            Rule.PLACEHOLDER: "Yer tutucu uyuşmazlığı",
            Rule.MISSING: "Eksik çeviri",
            Rule.SAME_AS_SOURCE: "Kaynakla aynı",
            Rule.PLURAL: "Çoğul grubu eksik",
            Rule.PARITY: "Parite",
            Rule.CONSISTENCY: "Tutarsız çeviri",
            Rule.WHITESPACE: "Boşluk farkı",
            Rule.STRAY_TURKISH: "Kaçak Türkçe metin",
        }[self]


#: Varsayılan olarak açık kurallar ve önem dereceleri.
RULES: Dict[Rule, Severity] = {
    Rule.PLACEHOLDER: Severity.ERROR,
    Rule.MISSING: Severity.WARNING,
    Rule.SAME_AS_SOURCE: Severity.WARNING,
    Rule.PLURAL: Severity.ERROR,
    Rule.PARITY: Severity.WARNING,
    Rule.CONSISTENCY: Severity.INFO,
    Rule.WHITESPACE: Severity.INFO,
    Rule.STRAY_TURKISH: Severity.WARNING,
}


@dataclass
class Issue:
    rule: Rule
    severity: Severity
    lang: str
    bundle: str
    key: str
    message: str

    @property
    def ref(self) -> KeyRef:
        return KeyRef(self.bundle, self.key)


def validate(
    project: Project,
    langs: Optional[Sequence[str]] = None,
    enabled: Optional[Sequence[Rule]] = None,
) -> List[Issue]:
    """Hedef diller için tüm açık kuralları çalıştırır."""
    targets = list(langs) if langs else [
        lang for lang in project.languages if lang != project.source_lang
    ]
    active = set(enabled) if enabled is not None else set(RULES)
    issues: List[Issue] = []

    for lang in targets:
        issues.extend(_check_language(project, lang, active))
    if Rule.PARITY in active:
        issues.extend(_check_parity(project, targets))
    return issues


def _check_language(project: Project, lang: str, active: set[Rule]) -> List[Issue]:
    issues: List[Issue] = []
    # Tutarlılık için: kaynak metin -> gördüğümüz çeviriler
    by_source: Dict[str, Dict[str, List[KeyRef]]] = defaultdict(lambda: defaultdict(list))
    plural_bases: Dict[tuple[str, str], set[str]] = defaultdict(set)

    for ref in project.key_order:
        source = project.source_value(ref)
        target = project.value(ref, lang)
        status = key_status(source, target)

        group = plural_group(ref.key)
        if group:
            plural_bases[(ref.bundle, group[0])].add(group[1])

        if status is KeyStatus.MISSING:
            if Rule.MISSING in active:
                issues.append(
                    Issue(
                        Rule.MISSING,
                        RULES[Rule.MISSING],
                        lang,
                        ref.bundle,
                        ref.key,
                        "Çeviri yok veya boş",
                    )
                )
            continue

        assert target is not None
        if status is KeyStatus.SAME_AS_SOURCE and Rule.SAME_AS_SOURCE in active:
            issues.append(
                Issue(
                    Rule.SAME_AS_SOURCE,
                    RULES[Rule.SAME_AS_SOURCE],
                    lang,
                    ref.bundle,
                    ref.key,
                    "Değer kaynak dille birebir aynı",
                )
            )

        if Rule.PLACEHOLDER in active:
            expected, actual = placeholders(source), placeholders(target)
            if expected != actual:
                missing = sorted(expected - actual)
                extra = sorted(actual - expected)
                parts = []
                if missing:
                    parts.append("eksik " + ", ".join("{%s}" % n for n in missing))
                if extra:
                    parts.append("fazla " + ", ".join("{%s}" % n for n in extra))
                issues.append(
                    Issue(
                        Rule.PLACEHOLDER,
                        RULES[Rule.PLACEHOLDER],
                        lang,
                        ref.bundle,
                        ref.key,
                        "Yer tutucu: " + "; ".join(parts),
                    )
                )

        if Rule.WHITESPACE in active and source:
            if (source[:1].isspace() != target[:1].isspace()) or (
                source[-1:].isspace() != target[-1:].isspace()
            ):
                issues.append(
                    Issue(
                        Rule.WHITESPACE,
                        RULES[Rule.WHITESPACE],
                        lang,
                        ref.bundle,
                        ref.key,
                        "Baştaki/sondaki boşluk kaynaktan farklı",
                    )
                )

        if Rule.STRAY_TURKISH in active and lang != "tr" and has_turkish_chars(target):
            issues.append(
                Issue(
                    Rule.STRAY_TURKISH,
                    RULES[Rule.STRAY_TURKISH],
                    lang,
                    ref.bundle,
                    ref.key,
                    "Türkçeye özgü harf içeriyor — çevrilmemiş olabilir",
                )
            )

        if Rule.CONSISTENCY in active and source and len(source) > 3:
            by_source[source][target].append(ref)

    if Rule.PLURAL in active:
        issues.extend(_check_plurals(project, lang, plural_bases))

    if Rule.CONSISTENCY in active:
        for source, variants in by_source.items():
            if len(variants) < 2:
                continue
            for translation, refs in variants.items():
                for ref in refs:
                    issues.append(
                        Issue(
                            Rule.CONSISTENCY,
                            RULES[Rule.CONSISTENCY],
                            lang,
                            ref.bundle,
                            ref.key,
                            'Aynı kaynak metin (%s…) %d farklı şekilde çevrilmiş'
                            % (source[:30], len(variants)),
                        )
                    )

    return issues


def _check_plurals(
    project: Project, lang: str, plural_bases: Dict[tuple[str, str], set[str]]
) -> List[Issue]:
    """Kaynakta var olan çoğul kategorileri hedefte de olmalı."""
    issues: List[Issue] = []
    for (bundle, base), categories in plural_bases.items():
        expected = {
            cat
            for cat in categories
            if project.value(KeyRef(bundle, f"{base}.{cat}"), project.source_lang)
        }
        for cat in sorted(expected, key=PLURAL_SUFFIXES.index):
            key = f"{base}.{cat}"
            value = project.value(KeyRef(bundle, key), lang)
            if value is None:
                issues.append(
                    Issue(
                        Rule.PLURAL,
                        RULES[Rule.PLURAL],
                        lang,
                        bundle,
                        key,
                        f"Çoğul grubu '{base}' için '.{cat}' anahtarı yok",
                    )
                )
    return issues


def _check_parity(project: Project, targets: Sequence[str]) -> List[Issue]:
    issues: List[Issue] = []
    for bundle, files in sorted(project.bundles.items()):
        source = files.get(project.source_lang)
        for lang in targets:
            arb = files.get(lang)
            if arb is None:
                issues.append(
                    Issue(
                        Rule.PARITY,
                        RULES[Rule.PARITY],
                        lang,
                        bundle,
                        "",
                        f"'{bundle}' dosyası bu dilde hiç yok",
                    )
                )
                continue
            if source is None:
                continue
            for key in arb.keys():
                if key not in source.entries:
                    issues.append(
                        Issue(
                            Rule.PARITY,
                            RULES[Rule.PARITY],
                            lang,
                            bundle,
                            key,
                            "Anahtar kaynak dilde yok (öksüz)",
                        )
                    )
    return issues
