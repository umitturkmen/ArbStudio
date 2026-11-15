"""Klasör taraması ve dil tespiti."""

from __future__ import annotations

from pathlib import Path

from arbstudio.model import Project
from arbstudio.model.project import is_lang_tag, normalize_lang
from conftest import requires_islam365, write_arb


def test_folder_layout(sample_project: Project):
    assert sample_project.languages == ["en", "tr"]
    assert sorted(sample_project.bundles) == ["common.arb", "tools.arb"]
    assert sample_project.key_count == 11


def test_filename_suffix_layout(tmp_path: Path):
    """Düz Flutter düzeni: lib/l10n/app_tr.arb"""
    write_arb(tmp_path / "l10n" / "app_tr.arb", "tr", {"k": "v"})
    write_arb(tmp_path / "l10n" / "app_en.arb", "en", {"k": "v"})
    project = Project.scan(tmp_path)
    assert project.languages == ["en", "tr"]
    assert list(project.bundles) == ["app.arb"]


def test_locale_field_fallback(tmp_path: Path):
    """Ne klasör ne dosya adı ipucu verirse @@locale kullanılır."""
    write_arb(tmp_path / "strings" / "messages.arb", "de", {"k": "v"})
    project = Project.scan(tmp_path)
    assert project.languages == ["de"]


def test_non_language_folder_is_not_mistaken(tmp_path: Path):
    write_arb(tmp_path / "assets" / "help_support.arb", "tr", {"k": "v"})
    project = Project.scan(tmp_path)
    # 'assets' dil kodu değil, 'help_support' eki de değil -> @@locale devreye girer
    assert project.languages == ["tr"]
    assert list(project.bundles) == ["help_support.arb"]


def test_broken_json_is_reported_not_fatal(tmp_path: Path):
    write_arb(tmp_path / "tr" / "ok.arb", "tr", {"k": "v"})
    (tmp_path / "tr" / "bad.arb").write_text("{ not json", encoding="utf-8")
    project = Project.scan(tmp_path)
    assert list(project.bundles) == ["ok.arb"]
    assert any("bad.arb" in error for error in project.load_errors)


def test_lang_tag_helpers():
    assert is_lang_tag("tr") and is_lang_tag("pt_BR") and is_lang_tag("zh-Hant")
    assert not is_lang_tag("assets") and not is_lang_tag("support")
    assert normalize_lang("pt-br") == "pt_BR"


@requires_islam365
def test_islam365_shape(islam365_copy: Path):
    project = Project.scan(islam365_copy, source_lang="tr")
    # Dil listesi zamanla büyüyebilir (ar, de … eklenince); kaynak çift sabit.
    assert {"en", "tr"} <= set(project.languages)
    assert len(project.bundles) == 15
    assert project.key_count == 2976
    assert project.load_errors == []
