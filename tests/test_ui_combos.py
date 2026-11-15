"""Açılır menülerden okunan veri regresyon testleri.

Arka plan: `str` tabanlı enum'lar (`class FilterMode(str, Enum)`) QComboBox
userData'sına konduğunda Qt onları düz `str`'e çeviriyor. Geri okunan değer
enum olmadığı için `is` karşılaştırmaları sessizce yanlış sonuç veriyor ve
`.value` erişimi AttributeError fırlatıyordu — dışa aktarma manifesti hiç
yazılmıyor, sol paneldeki 'Tümü' filtresi listeyi boşaltıyordu.

Bu testler kodu değil, **açılır menü yolunu** dener.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from arbstudio.model import Project  # noqa: E402
from arbstudio.services.validator import Rule, Severity, validate  # noqa: E402
from arbstudio.txtio import ExportFormat  # noqa: E402
from arbstudio.txtio.txt_import import read_lines  # noqa: E402
from arbstudio.ui.dialogs import ExportDialog  # noqa: E402
from arbstudio.ui.issues_panel import IssuesPanel  # noqa: E402
from arbstudio.ui.key_list import FilterMode, KeyListPanel  # noqa: E402
from arbstudio.ui.qtutil import combo_enum  # noqa: E402


@pytest.fixture(scope="module")
def app():
    yield QApplication.instance() or QApplication([])


def test_combo_enum_survives_qt_string_conversion(app):
    from PySide6.QtWidgets import QComboBox

    box = QComboBox()
    for mode in FilterMode:
        box.addItem(mode.label, mode)
    box.setCurrentIndex(0)
    # Qt'nin ham verisi düz str'e dönmüş olabilir; yardımcı yine enum döndürmeli.
    assert combo_enum(box, FilterMode) is FilterMode.ALL
    box.setCurrentIndex(2)
    assert isinstance(combo_enum(box, FilterMode), FilterMode)


def test_combo_enum_handles_none_and_garbage(app):
    from PySide6.QtWidgets import QComboBox

    box = QComboBox()
    box.addItem("boş", None)
    box.addItem("çöp", "yok_boyle_deger")
    box.setCurrentIndex(0)
    assert combo_enum(box, FilterMode, FilterMode.ALL) is FilterMode.ALL
    box.setCurrentIndex(1)
    assert combo_enum(box, FilterMode, FilterMode.ALL) is FilterMode.ALL


def test_filter_combo_selects_all(app, sample_project: Project):
    panel = KeyListPanel()
    panel.set_project(sample_project)
    total = sample_project.key_count

    panel.mode_box.setCurrentIndex(0)  # "Tümü"
    assert panel.model._mode is FilterMode.ALL
    assert len(panel.model.rows) == total

    index = [m for m in FilterMode].index(FilterMode.WITH_PLACEHOLDER)
    panel.mode_box.setCurrentIndex(index)
    assert panel.model._mode is FilterMode.WITH_PLACEHOLDER
    assert 0 < len(panel.model.rows) < total

    panel.mode_box.setCurrentIndex(0)
    assert len(panel.model.rows) == total


def test_bundle_combo_filters(app, sample_project: Project):
    panel = KeyListPanel()
    panel.set_project(sample_project)
    index = panel.bundle_box.findData("tools.arb")
    panel.bundle_box.setCurrentIndex(index)
    assert {r.bundle for r in panel.model.rows} == {"tools.arb"}
    panel.bundle_box.setCurrentIndex(0)
    assert len(panel.model.rows) == sample_project.key_count


def test_issue_filters_via_combo(app, sample_project: Project):
    from arbstudio.model import KeyRef

    sample_project.set_value(KeyRef("common.arb", "greeting"), "en", "Hello")
    sample_project.set_value(KeyRef("common.arb", "save"), "en", "Kaydet")
    panel = IssuesPanel()
    panel.set_issues(validate(sample_project, ["en"]))
    total_rows = panel.table.rowCount()
    assert total_rows > 0

    index = panel.severity_box.findData(Severity.ERROR)
    panel.severity_box.setCurrentIndex(index)
    assert panel.table.rowCount() < total_rows
    assert panel.table.rowCount() > 0  # placeholder hatası var

    panel.severity_box.setCurrentIndex(0)
    assert panel.table.rowCount() == total_rows

    index = panel.rule_box.findData(Rule.PLACEHOLDER)
    if index >= 0:
        panel.rule_box.setCurrentIndex(index)
        assert 0 < panel.table.rowCount() < total_rows


@pytest.mark.parametrize("fmt_index", [0, 1])
def test_export_dialog_writes_txt_and_manifest(
    app, sample_project: Project, tmp_path: Path, monkeypatch, fmt_index: int
):
    """Asıl regresyon: biçim menüsünden okunan değer manifesti bozmamalı."""
    seen = []
    monkeypatch.setattr(
        QMessageBox,
        "information",
        staticmethod(lambda *a, **k: seen.append(a)),
    )

    dialog = ExportDialog(sample_project, "", [], None)
    dialog.format_box.setCurrentIndex(fmt_index)
    out = tmp_path / "cikti.txt"
    dialog.path_edit.setText(str(out))
    dialog._export()

    expected_fmt = list(ExportFormat)[fmt_index]
    assert seen, "başarı mesajı gösterilmedi (istisna yutulmuş olabilir)"
    assert out.exists()
    assert (tmp_path / "cikti.arbmap.json").exists(), "manifest yazılmadı"

    lines = read_lines(out)
    assert len(lines) == sample_project.key_count
    has_tab = any("\t" in line for line in lines)
    assert has_tab is (expected_fmt is ExportFormat.TSV)

    import json

    manifest = json.loads((tmp_path / "cikti.arbmap.json").read_text(encoding="utf-8"))
    assert manifest["format"] == expected_fmt.value
    assert manifest["line_count"] == sample_project.key_count


def test_export_scope_combo_limits_keys(
    app, sample_project: Project, tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))
    dialog = ExportDialog(sample_project, "", [], None)
    index = next(
        i
        for i in range(dialog.scope_box.count())
        if dialog.scope_box.itemData(i) == ("bundle", "tools.arb")
    )
    dialog.scope_box.setCurrentIndex(index)
    out = tmp_path / "tools.txt"
    dialog.path_edit.setText(str(out))
    dialog._export()
    assert len(read_lines(out)) == len(sample_project.keys_of("tools.arb"))
