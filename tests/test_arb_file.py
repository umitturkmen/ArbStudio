"""Bayt-sadıklık ve ARB okuma/yazma testleri."""

from __future__ import annotations

from pathlib import Path

import pytest

from arbstudio.model import ArbFile, FileStyle
from conftest import ISLAM365, requires_islam365, write_arb


@requires_islam365
def test_islam365_roundtrip_is_byte_identical():
    """Gerçek projedeki 30 dosya, dokunulmadan yeniden yazılınca birebir aynı olmalı."""
    paths = sorted(ISLAM365.rglob("*.arb"))
    assert len(paths) >= 30, "beklenen dosya sayısı bulunamadı"
    for path in paths:
        arb = ArbFile.load(path, path.parent.name)
        assert arb.serialize() == path.read_bytes(), f"bayt farkı: {path}"


@pytest.mark.parametrize("newline", ["\r\n", "\n"])
def test_newline_style_preserved(tmp_path: Path, newline: str):
    path = write_arb(tmp_path / "a.arb", "tr", {"k": "v"}, newline=newline)
    arb = ArbFile.load(path, "tr")
    assert arb.style.newline == newline
    assert arb.serialize() == path.read_bytes()


def test_bom_and_indent_detected(tmp_path: Path):
    path = tmp_path / "b.arb"
    body = '{\n    "@@locale": "tr",\n    "k": "v"\n}\n'
    path.write_bytes(b"\xef\xbb\xbf" + body.encode("utf-8"))
    arb = ArbFile.load(path, "tr")
    assert arb.style.bom is True
    assert arb.style.indent == 4
    assert arb.serialize() == path.read_bytes()


def test_ascii_escaped_file_stays_escaped(tmp_path: Path):
    path = tmp_path / "c.arb"
    path.write_bytes(b'{\n  "@@locale": "tr",\n  "k": "G\\u00fcn"\n}\n')
    arb = ArbFile.load(path, "tr")
    assert arb.style.ensure_ascii is True
    assert arb.get("k") == "Gün"
    assert arb.serialize() == path.read_bytes()


def test_rename_preserves_key_order(tmp_path: Path):
    path = write_arb(tmp_path / "d.arb", "tr", {"a": "1", "b": "2", "c": "3"})
    arb = ArbFile.load(path, "tr")
    assert arb.rename("b", "bb") is True
    assert list(arb.keys()) == ["a", "bb", "c"]


def test_save_creates_sibling_backup_when_no_dir_given(tmp_path: Path):
    path = write_arb(tmp_path / "e.arb", "tr", {"a": "1"})
    arb = ArbFile.load(path, "tr")
    arb.set("a", "2")
    assert arb.dirty is True
    arb.save()
    assert arb.dirty is False
    assert (tmp_path / "e.arb.bak").exists()
    assert ArbFile.load(path, "tr").get("a") == "2"


def test_backup_dir_mirrors_relative_path(tmp_path: Path):
    path = write_arb(tmp_path / "en" / "common.arb", "en", {"a": "1"})
    arb = ArbFile.load(path, "en")
    arb.set("a", "2")
    arb.save(backup_dir=tmp_path / ".arbstudio-backups")

    backup = tmp_path / ".arbstudio-backups" / "en" / "common.arb"
    assert backup.exists(), "yedek klasöre yazılmadı"
    assert not (path.parent / "common.arb.bak").exists(), "yan yana .bak bırakılmış"
    assert ArbFile.load(backup, "en").get("a") == "1"  # eski içerik
    assert ArbFile.load(path, "en").get("a") == "2"  # yeni içerik


def test_set_returns_false_when_unchanged(tmp_path: Path):
    path = write_arb(tmp_path / "f.arb", "tr", {"a": "1"})
    arb = ArbFile.load(path, "tr")
    assert arb.set("a", "1") is False
    assert arb.dirty is False
