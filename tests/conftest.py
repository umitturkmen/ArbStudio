from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from arbstudio.model import ArbFile, Project

#: Gerçek dünya testleri için İslam 365 çeviri klasörü (varsa).
ISLAM365 = Path(r"C:/Projects/IslamiHesapMakinesi/assets/translations")

requires_islam365 = pytest.mark.skipif(
    not ISLAM365.exists(), reason="İslam 365 çeviri klasörü bulunamadı"
)


def write_arb(path: Path, locale: str, entries: dict, newline: str = "\r\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"@@locale": locale, **entries}
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    path.write_bytes(text.replace("\n", newline).encode("utf-8"))
    return path


@pytest.fixture
def sample_project(tmp_path: Path) -> Project:
    """İki dilli küçük proje: yer tutucu, çoğul ve çok satırlı değerler içerir."""
    write_arb(
        tmp_path / "tr" / "common.arb",
        "tr",
        {
            "save": "Kaydet",
            "greeting": "Merhaba {name}!",
            "pages": "Sayfa {page} / {total}",
            "multiline": "Birinci satır\nİkinci satır",
            "tabbed": "Sol\tSağ",
            "backslash": "C:\\yol\\dosya",
            "days.one": "{count} gün",
            "days.other": "{count} gün",
            "empty_here": "",
        },
    )
    write_arb(
        tmp_path / "en" / "common.arb",
        "en",
        {
            "save": "Save",
            "greeting": "Hello {name}!",
            "pages": "Page {page} / {total}",
            "multiline": "First line\nSecond line",
            "tabbed": "Left\tRight",
            "backslash": "C:\\path\\file",
            "days.one": "{count} day",
            "days.other": "{count} days",
            "empty_here": "",
        },
    )
    write_arb(
        tmp_path / "tr" / "tools.arb",
        "tr",
        {"calc": "Hesapla", "result": "Sonuç: {value}"},
    )
    write_arb(
        tmp_path / "en" / "tools.arb",
        "en",
        {"calc": "Calculate", "result": "Result: {value}"},
    )
    return Project.scan(tmp_path, source_lang="tr")


@pytest.fixture
def islam365_copy(tmp_path: Path) -> Path:
    if not ISLAM365.exists():
        pytest.skip("İslam 365 çeviri klasörü bulunamadı")
    target = tmp_path / "translations"
    shutil.copytree(ISLAM365, target)
    return target


@pytest.fixture(scope="session", autouse=True)
def _offscreen_qt():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
