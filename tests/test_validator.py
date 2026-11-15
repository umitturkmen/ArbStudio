"""Doğrulama kuralları — her kural için pozitif ve negatif örnek."""

from __future__ import annotations

from arbstudio.model import KeyRef, Project
from arbstudio.services.validator import Rule, Severity, validate
from conftest import requires_islam365


def _rules(project: Project, lang: str = "en") -> set[Rule]:
    return {issue.rule for issue in validate(project, [lang])}


def _for_key(project: Project, key: str, lang: str = "en"):
    return [issue for issue in validate(project, [lang]) if issue.key == key]


def test_clean_project_has_no_errors(sample_project: Project):
    issues = validate(sample_project, ["en"])
    assert not [i for i in issues if i.severity is Severity.ERROR]


def test_placeholder_mismatch_detected(sample_project: Project):
    ref = KeyRef("common.arb", "greeting")
    sample_project.set_value(ref, "en", "Hello there!")
    issues = _for_key(sample_project, "greeting")
    assert any(i.rule is Rule.PLACEHOLDER for i in issues)
    assert any("{name}" in i.message for i in issues)


def test_extra_placeholder_detected(sample_project: Project):
    sample_project.set_value(KeyRef("common.arb", "save"), "en", "Save {oops}")
    assert any(i.rule is Rule.PLACEHOLDER for i in _for_key(sample_project, "save"))


def test_missing_translation_detected(sample_project: Project):
    sample_project.set_value(KeyRef("common.arb", "save"), "en", "   ")
    assert any(i.rule is Rule.MISSING for i in _for_key(sample_project, "save"))


def test_same_as_source_detected(sample_project: Project):
    sample_project.set_value(KeyRef("common.arb", "save"), "en", "Kaydet")
    assert any(i.rule is Rule.SAME_AS_SOURCE for i in _for_key(sample_project, "save"))


def test_missing_plural_category_detected(sample_project: Project):
    en = sample_project.file("common.arb", "en")
    assert en is not None
    en.remove("days.other")
    issues = _for_key(sample_project, "days.other")
    assert any(i.rule is Rule.PLURAL for i in issues)


def test_complete_plural_group_is_clean(sample_project: Project):
    assert not [
        i for i in validate(sample_project, ["en"]) if i.rule is Rule.PLURAL
    ]


def test_orphan_key_reported_as_parity(sample_project: Project):
    en = sample_project.file("common.arb", "en")
    assert en is not None
    en.set("only_in_english", "orphan")
    sample_project.rebuild_key_order()
    assert any(
        i.rule is Rule.PARITY and i.key == "only_in_english"
        for i in validate(sample_project, ["en"])
    )


def test_missing_bundle_reported_as_parity(sample_project: Project):
    del sample_project.bundles["tools.arb"]["en"]
    issues = [i for i in validate(sample_project, ["en"]) if i.rule is Rule.PARITY]
    assert any("tools.arb" in i.message for i in issues)


def test_stray_turkish_chars_detected(sample_project: Project):
    sample_project.set_value(KeyRef("common.arb", "save"), "en", "Kaydetme işlemi")
    assert any(i.rule is Rule.STRAY_TURKISH for i in _for_key(sample_project, "save"))


def test_stray_turkish_not_reported_for_turkish_target(sample_project: Project):
    sample_project.source_lang = "en"
    sample_project.rebuild_key_order()
    assert not [
        i for i in validate(sample_project, ["tr"]) if i.rule is Rule.STRAY_TURKISH
    ]


def test_whitespace_difference_detected(sample_project: Project):
    sample_project.set_value(KeyRef("common.arb", "save"), "en", "Save ")
    assert any(i.rule is Rule.WHITESPACE for i in _for_key(sample_project, "save"))


def test_inconsistent_translation_detected(sample_project: Project):
    project = sample_project
    project.add_key("common.arb", "save_two", "Kaydet")
    project.set_value(KeyRef("common.arb", "save_two"), "en", "Store")
    issues = [i for i in validate(project, ["en"]) if i.rule is Rule.CONSISTENCY]
    assert {i.key for i in issues} >= {"save", "save_two"}


def test_disabled_rule_is_skipped(sample_project: Project):
    sample_project.set_value(KeyRef("common.arb", "save"), "en", "Kaydet")
    issues = validate(sample_project, ["en"], enabled=[Rule.PLACEHOLDER])
    assert not [i for i in issues if i.rule is Rule.SAME_AS_SOURCE]


@requires_islam365
def test_islam365_has_no_placeholder_or_plural_errors(islam365_copy):
    project = Project.scan(islam365_copy, source_lang="tr")
    issues = validate(project, ["en"])
    assert not [i for i in issues if i.rule is Rule.PLACEHOLDER]
    assert not [i for i in issues if i.rule is Rule.PLURAL]
    assert not [i for i in issues if i.rule is Rule.PARITY]
