"""Anahtar yönetimi ve yeni dil ekleme."""

from __future__ import annotations

from pathlib import Path

import pytest

from arbstudio.model import ArbFile, KeyRef, Project


def test_add_key_creates_in_all_languages(sample_project: Project):
    ref = sample_project.add_key("common.arb", "new_key", "Yeni")
    assert sample_project.value(ref, "tr") == "Yeni"
    assert sample_project.value(ref, "en") == ""
    assert ref in sample_project.key_order


def test_add_duplicate_key_raises(sample_project: Project):
    with pytest.raises(ValueError):
        sample_project.add_key("common.arb", "save", "x")


def test_rename_key_across_languages(sample_project: Project):
    ref = sample_project.rename_key(KeyRef("common.arb", "save"), "store")
    assert ref.key == "store"
    assert sample_project.value(ref, "tr") == "Kaydet"
    assert sample_project.value(ref, "en") == "Save"
    assert KeyRef("common.arb", "save") not in sample_project.key_order


def test_delete_key_across_languages(sample_project: Project):
    removed = sample_project.delete_key(KeyRef("common.arb", "save"))
    assert removed == 2
    assert KeyRef("common.arb", "save") not in sample_project.key_order


def test_move_key_between_bundles(sample_project: Project):
    ref = sample_project.move_key(KeyRef("common.arb", "save"), "tools.arb")
    assert ref.bundle == "tools.arb"
    assert sample_project.value(ref, "en") == "Save"
    assert sample_project.file("common.arb", "en").entries.get("save") is None


def test_add_language_creates_all_bundles(sample_project: Project, tmp_path: Path):
    created = sample_project.add_language("ar")
    assert len(created) == len(sample_project.bundles)
    assert "ar" in sample_project.languages
    for ref in sample_project.key_order:
        assert sample_project.value(ref, "ar") == ""

    sample_project.save_all()
    for path in created:
        assert path.exists()
        reloaded = ArbFile.load(path, "ar")
        assert reloaded.locale == "ar"
        assert len(reloaded) == len(
            sample_project.file(path.name, sample_project.source_lang)
        )


def test_add_language_copy_values(sample_project: Project):
    sample_project.add_language("az", copy_values=True)
    ref = KeyRef("common.arb", "save")
    assert sample_project.value(ref, "az") == "Kaydet"


def test_add_existing_language_raises(sample_project: Project):
    with pytest.raises(ValueError):
        sample_project.add_language("en")


def test_new_language_files_match_source_layout(sample_project: Project):
    created = sample_project.add_language("fr")
    for path in created:
        assert path.parent.name == "fr"
        assert path.parent.parent == sample_project.root


def test_dirty_tracking_and_save(sample_project: Project):
    assert sample_project.is_dirty is False
    sample_project.set_value(KeyRef("common.arb", "save"), "en", "Saved")
    assert len(sample_project.dirty_files) == 1
    saved = sample_project.save_all()
    assert len(saved) == 1
    assert sample_project.is_dirty is False


def test_backups_go_to_one_folder_not_beside_files(sample_project: Project):
    sample_project.set_value(KeyRef("common.arb", "save"), "en", "Saved")
    sample_project.save_all()

    assert (sample_project.backup_dir / "en" / "common.arb").exists()
    assert not list(sample_project.root.rglob("*.arb.bak")), "yan yana .bak kalmış"


def test_backup_folder_is_not_rescanned_as_project_data(sample_project: Project):
    """Yedekler gerçek .arb dosyaları — tarama onları proje sanmamalı."""
    sample_project.set_value(KeyRef("common.arb", "save"), "en", "Saved")
    sample_project.save_all()

    rescanned = Project.scan(sample_project.root, source_lang="tr")
    assert rescanned.languages == ["en", "tr"]
    assert rescanned.key_count == sample_project.key_count
    assert rescanned.load_errors == []


def test_stats_reflect_state(sample_project: Project):
    stats = sample_project.stats("en")["__total__"]
    assert stats.total == sample_project.key_count
    sample_project.add_language("de")
    de = sample_project.stats("de")["__total__"]
    assert de.translated == 0
    assert de.missing == de.total
