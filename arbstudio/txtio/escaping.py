"""Satır bazlı TXT için kaçış kuralları.

Bir değer TXT'de **tek satır** kaplamak zorunda (satır N = anahtar N). Bu yüzden
yalnızca üç dizi kaçırılır:

    ters bölü  \\  ->  \\\\
    satır sonu \\n ->  \\n
    sekme      \\t ->  \\t

Bu, çevirmenin gördüğü metni bozmayacak kadar dar; `\\n` gördüğü yere satır sonu
koyması yeterli. Dönüşüm tam tersine çevrilebilir: unescape(escape(x)) == x.
"""

from __future__ import annotations

import re

_UNESCAPE_RE = re.compile(r"\\(.)")
_UNESCAPE_MAP = {"n": "\n", "t": "\t", "\\": "\\"}


def escape_value(value: str) -> str:
    if not value:
        return ""
    # Sıra önemli: önce ters bölü, sonra diğerleri.
    out = value.replace("\\", "\\\\")
    out = out.replace("\r\n", "\\n").replace("\r", "\\n").replace("\n", "\\n")
    return out.replace("\t", "\\t")


def unescape_value(text: str) -> str:
    if not text:
        return ""

    def repl(match: re.Match[str]) -> str:
        char = match.group(1)
        # Tanınmayan kaçışlar (\u1234 gibi) olduğu gibi bırakılır.
        return _UNESCAPE_MAP.get(char, "\\" + char)

    return _UNESCAPE_RE.sub(repl, text)
