"""Anahtar düzeyi yardımcılar: placeholder, çoğul grubu, çeviri durumu."""

from __future__ import annotations

import re
from enum import Enum
from typing import Optional, Set, Tuple

#: ARB/ICU çoğul kategorileri. Projede `anahtar.one` / `anahtar.other` deseni kullanılıyor.
PLURAL_SUFFIXES = ("zero", "one", "two", "few", "many", "other")

_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")
_PLURAL_RE = re.compile(r"^(?P<base>.+)\.(?P<cat>%s)$" % "|".join(PLURAL_SUFFIXES))

#: Türkçeye özgü harfler — hedef dil tr değilken kaçak metin göstergesi.
TURKISH_CHARS = set("ğĞşŞıİçÇöÖüÜ")


class KeyStatus(str, Enum):
    MISSING = "missing"          # hedefte yok ya da boş
    SAME_AS_SOURCE = "same"      # kaynakla birebir aynı — muhtemelen çevrilmemiş
    TRANSLATED = "translated"


def placeholders(text: str) -> Set[str]:
    """`{count}` biçimindeki yer tutucu adlarını döndürür."""
    if not text:
        return set()
    return set(_PLACEHOLDER_RE.findall(text))


def plural_group(key: str) -> Optional[Tuple[str, str]]:
    """`stats_days_count.one` → `("stats_days_count", "one")`, değilse None."""
    match = _PLURAL_RE.match(key)
    if not match:
        return None
    return match.group("base"), match.group("cat")


def key_status(source: str, target: Optional[str]) -> KeyStatus:
    if target is None or not target.strip():
        return KeyStatus.MISSING
    if source and target == source:
        return KeyStatus.SAME_AS_SOURCE
    return KeyStatus.TRANSLATED


def has_turkish_chars(text: str) -> bool:
    return any(ch in TURKISH_CHARS for ch in text)
