"""Arayüz duman testleri (offscreen)."""

from __future__ import annotations

from pathlib import Path

import pytest

from arbstudio.model import KeyRef

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from arbstudio.ui.key_list import FilterMode  # noqa: E402
from arbstudio.ui.main_window import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    yield instance


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings

    # Testler kullanıcının gerçek ayarlarına dokunmasın.
    QSettings.setDefaultFormat(QSettings.IniFormat)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    win = MainWindow()
    yield win
    win.project = None
    win.close()


def _make_project(tmp_path: Path) -> Path:
    from conftest import write_arb

    root = tmp_path / "proj"
    write_arb(
        root / "tr" / "common.arb",
        "tr",
        {"save": "Kaydet", "hi": "Merhaba {name}", "days.one": "{n} gün",
         "days.other": "{n} gün"},
    )
    write_arb(
        root / "en" / "common.arb",
        "en",
        {"save": "Save", "hi": "Hello {name}", "days.one": "{n} day",
         "days.other": "{n} days"},
    )
    return root


def test_load_project_populates_panels(window, tmp_path):
    window.load_project(_make_project(tmp_path))
    assert window.project is not None
    assert window.project.languages == ["en", "tr"]
    assert len(window.key_panel.model.rows) == 4
    assert window.stats.table.rowCount() == 2  # common.arb + TOPLAM


def test_selecting_key_builds_editors(window, tmp_path):
    window.load_project(_make_project(tmp_path))
    ref = KeyRef("common.arb", "save")
    assert window.key_panel.select_ref(ref) is True
    assert len(window.editor._editors) == 2  # tr + en


def test_plural_group_shown_together(window, tmp_path):
    window.load_project(_make_project(tmp_path))
    window.key_panel.select_ref(KeyRef("common.arb", "days.one"))
    assert {r.key for r in window.editor.refs} == {"days.one", "days.other"}


def test_editing_marks_dirty(window, tmp_path):
    window.load_project(_make_project(tmp_path))
    ref = KeyRef("common.arb", "save")
    window._on_value_edited(ref, "en", "Store")
    assert window.project.is_dirty is True
    assert window.project.value(ref, "en") == "Store"


def test_filters_narrow_the_list(window, tmp_path):
    root = _make_project(tmp_path)
    window.load_project(root)
    window.key_panel.model.set_filters(mode=FilterMode.WITH_PLACEHOLDER)
    assert len(window.key_panel.model.rows) == 3  # hi + days.one + days.other
    window.key_panel.model.set_filters(mode=FilterMode.ALL, search="kaydet")
    assert [r.key for r in window.key_panel.model.rows] == ["save"]


def test_validation_populates_issue_panel(window, tmp_path):
    window.load_project(_make_project(tmp_path))
    window._on_value_edited(KeyRef("common.arb", "hi"), "en", "Hello")  # {name} kayıp
    window.run_validation()
    assert any(i.key == "hi" for i in window.issues.issues)
    assert "Doğrulama" in window.bottom_tabs.tabText(0)


def test_jump_from_issue_selects_key(window, tmp_path):
    window.load_project(_make_project(tmp_path))
    window._on_value_edited(KeyRef("common.arb", "hi"), "en", "Hello")
    window.run_validation()
    window._jump_to(KeyRef("common.arb", "hi"))
    assert window.key_panel.current_ref() == KeyRef("common.arb", "hi")


def test_new_language_updates_source_box(window, tmp_path):
    window.load_project(_make_project(tmp_path))
    window.project.add_language("de")
    window.key_panel.model.refresh()
    window.stats.update_stats(window.project)
    assert "de" in window.project.languages
    assert window.stats.table.columnCount() == 3  # dosya + en + de (kaynak tr)
