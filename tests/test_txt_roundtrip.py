"""TXT dışa/içe aktarma: kaçış, roundtrip, hizalama denetimi."""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from arbstudio.model import Project
from arbstudio.txtio import (
    ExportFormat,
    ImportAction,
    build_import_plan,
    escape_value,
    export_txt,
    unescape_value,
)
from arbstudio.txtio.txt_import import detect_format, read_lines
from conftest import requires_islam365

TRICKY = [
    "",
    "düz metin",
    "iki\nsatır",
    "üç\nsatır\nvar",
    "sol\tsağ",
    "C:\\yol\\dosya",
    "karışık\\n literal ile gerçek\nsatır",
    "{count} gün · %50 — “tırnak”",
    "\\",
    "son satır sonu\n",
]


@pytest.mark.parametrize("value", TRICKY)
def test_escape_is_reversible(value: str):
    assert unescape_value(escape_value(value)) == value


@pytest.mark.parametrize("value", TRICKY)
def test_escaped_value_is_single_line(value: str):
    assert "\n" not in escape_value(value)
    assert "\t" not in escape_value(value)


def _rewrite(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig", newline="\r\n")


def test_lines_roundtrip_into_new_language(sample_project: Project, tmp_path: Path):
    project = sample_project
    project.add_language("de")
    out = tmp_path / "tr.txt"
    export_txt(project, "tr", project.key_order, out, ExportFormat.LINES)

    assert len(read_lines(out)) == project.key_count

    plan = build_import_plan(project, "de", out)
    assert plan.fmt is ExportFormat.LINES
    assert plan.manifest_used is True
    assert plan.is_risky is False
    plan.apply(project)

    for ref in project.key_order:
        assert project.value(ref, "de") == (project.value(ref, "tr") or "")


def test_multiline_value_survives(sample_project: Project, tmp_path: Path):
    project = sample_project
    project.add_language("de")
    out = tmp_path / "tr.txt"
    export_txt(project, "tr", project.key_order, out, ExportFormat.LINES)

    ref = next(r for r in project.key_order if r.key == "multiline")
    index = list(project.key_order).index(ref)
    assert read_lines(out)[index] == "Birinci satır\\nİkinci satır"

    build_import_plan(project, "de", out).apply(project)
    assert project.value(ref, "de") == "Birinci satır\nİkinci satır"


def test_deleted_line_is_caught_before_writing(sample_project: Project, tmp_path: Path):
    project = sample_project
    project.add_language("de")
    out = tmp_path / "tr.txt"
    export_txt(project, "tr", project.key_order, out, ExportFormat.LINES)

    lines = read_lines(out)
    # 'greeting' ({name}) satırını sil -> sonrasındaki her şey kayar
    victim = list(project.key_order).index(
        next(r for r in project.key_order if r.key == "greeting")
    )
    del lines[victim]
    bad = tmp_path / "bad.txt"
    _rewrite(bad, lines)
    (tmp_path / "bad.arbmap.json").write_bytes(
        (tmp_path / "tr.arbmap.json").read_bytes()
    )

    plan = build_import_plan(project, "de", bad)
    assert plan.count_mismatch is True
    assert plan.is_risky is True
    assert plan.divergence is not None
    assert plan.divergence.line_no == victim + 1


def test_extra_line_is_reported(sample_project: Project, tmp_path: Path):
    project = sample_project
    project.add_language("de")
    out = tmp_path / "tr.txt"
    export_txt(project, "tr", project.key_order, out, ExportFormat.LINES)

    lines = read_lines(out) + ["fazladan satır"]
    bad = tmp_path / "bad.txt"
    _rewrite(bad, lines)
    plan = build_import_plan(project, "de", bad, use_manifest=False)
    assert plan.is_risky is True
    assert any(row.action is ImportAction.UNKNOWN_KEY for row in plan.rows)


def test_empty_lines_do_not_erase_existing(sample_project: Project, tmp_path: Path):
    project = sample_project
    out = tmp_path / "blank.txt"
    _rewrite(out, ["" for _ in project.key_order])

    plan = build_import_plan(project, "en", out, use_manifest=False)
    assert all(row.action is ImportAction.SKIPPED_EMPTY for row in plan.rows)
    assert plan.apply(project) == 0
    assert project.value(next(iter(project.key_order)), "en") == "Save"


def test_write_empty_flag_clears_values(sample_project: Project, tmp_path: Path):
    project = sample_project
    out = tmp_path / "blank.txt"
    _rewrite(out, ["" for _ in project.key_order])

    plan = build_import_plan(project, "en", out, write_empty=True, use_manifest=False)
    plan.apply(project)
    assert project.value(next(iter(project.key_order)), "en") == ""


def test_tsv_survives_shuffling(sample_project: Project, tmp_path: Path):
    project = sample_project
    project.add_language("de")
    out = tmp_path / "tr.tsv.txt"
    export_txt(project, "tr", project.key_order, out, ExportFormat.TSV)

    lines = read_lines(out)
    assert detect_format(lines, {r.key for r in project.key_order}) is ExportFormat.TSV
    random.Random(7).shuffle(lines)
    shuffled = tmp_path / "shuffled.txt"
    _rewrite(shuffled, lines)

    plan = build_import_plan(project, "de", shuffled, use_manifest=False)
    assert plan.fmt is ExportFormat.TSV
    assert plan.is_risky is False
    plan.apply(project)
    for ref in project.key_order:
        assert project.value(ref, "de") == (project.value(ref, "tr") or "")


def test_unknown_tsv_key_is_flagged(sample_project: Project, tmp_path: Path):
    out = tmp_path / "t.txt"
    _rewrite(out, ["save\tKaydet", "yok_boyle_anahtar\tDeğer"])
    plan = build_import_plan(sample_project, "en", out, use_manifest=False)
    assert plan.fmt is ExportFormat.TSV
    assert "yok_boyle_anahtar" in plan.unknown_keys
    assert plan.is_risky is True


def test_placeholder_issue_is_flagged_per_row(sample_project: Project, tmp_path: Path):
    out = tmp_path / "t.txt"
    _rewrite(out, ["greeting\tHello there!"])  # {name} kayıp
    plan = build_import_plan(sample_project, "en", out, use_manifest=False)
    row = next(r for r in plan.rows if r.ref and r.ref.key == "greeting")
    assert "{name}" in row.placeholder_issue


@requires_islam365
def test_islam365_full_roundtrip(islam365_copy: Path, tmp_path: Path):
    project = Project.scan(islam365_copy, source_lang="tr")
    project.add_language("de")
    out = tmp_path / "tr_full.txt"
    result = export_txt(project, "tr", project.key_order, out, ExportFormat.LINES)
    assert result.line_count == 2976
    assert len(read_lines(out)) == 2976

    plan = build_import_plan(project, "de", out)
    assert plan.is_risky is False
    assert sum(1 for r in plan.rows if r.placeholder_issue) == 0
    plan.apply(project)
    for ref in project.key_order:
        assert project.value(ref, "de") == (project.value(ref, "tr") or "")
