"""Тесты для build_chapter.py — сборочного пайплайна план → numeric → verify.

Юнит-тесты ``validate_plan`` точечно бьют по каждому правилу схемы плана.
Интеграционные тесты гоняют ``run_build`` с **замоканным** ``verify_chapter``
(настоящий numeric_executor при этом работает по-настоящему — он локальный и
быстрый), проверяя секвенирование стадий, гейты и сведе́ние вердикта. Реальной
главы в репозитории сейчас нет, поэтому весь verify здесь замокан; smoke против
живого контента вернётся, когда появится первая настоящая глава.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# build_chapter сам добавляет scripts/ и mcp/ в sys.path при импорте.
SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import build_chapter as bc  # noqa: E402


# ─── хелперы ──────────────────────────────────────────────────────────


def _valid_plan(chapter_number: int = 5) -> dict:
    """Минимальный структурно-валидный план."""
    return {
        "chapter_number": chapter_number,
        "sections": [
            {"number": 1, "title": "Первый раздел"},
            {"number": 2, "title": "Второй раздел"},
        ],
        "bridge_to_next": {"summary": "далее", "promises": ["обещание"]},
        "new_terms_introduced": [{"term": "вектор", "definition": "элемент"}],
        "biohazards_in_chapter": [{"name": "деление на ноль", "section": 2}],
    }


def _mini_repo(
    tmp_path: Path,
    *,
    metadata: dict | None,
    draft: str | None = None,
    chapter: str | None = None,
    n: int = 5,
) -> Path:
    """Собрать мини-репо: chapters/chapter_NN с (опц.) планом/черновиком/главой."""
    cdir = tmp_path / "chapters" / f"chapter_{n:02d}"
    cdir.mkdir(parents=True)
    if metadata is not None:
        (cdir / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False), encoding="utf-8"
        )
    if draft is not None:
        (cdir / "draft.md").write_text(draft, encoding="utf-8")
    if chapter is not None:
        (cdir / "chapter.md").write_text(chapter, encoding="utf-8")
    return tmp_path


def _fake_verify(verdict: str = "ok", findings: list | None = None):
    """Фабрика заглушки verify_chapter с заданным вердиктом и находками.

    Если ``findings`` не переданы, а вердикт не ``ok`` — синтезируем одну
    находку нужной строгости, чтобы заглушка была согласованной: настоящий
    ``verify_chapter`` с вердиктом ``warn``/``fail`` всегда несёт хотя бы одну
    находку соответствующей строгости. Оркестратор сводит вердикт из находок
    всех стадий, поэтому без находки «голый» вердикт не дошёл бы до отчёта.
    """
    if findings is None:
        _sev = {"fail": "error", "warn": "warning"}.get(verdict)
        findings = (
            [
                {
                    "check": "check_structure",
                    "severity": _sev,
                    "code": "fake_finding",
                    "message": "synthetic",
                    "location": None,
                }
            ]
            if _sev
            else []
        )
    counts = {"error": 0, "warning": 0, "info": 0}
    for f in findings:
        if f["severity"] in counts:
            counts[f["severity"]] += 1

    def _fn(root, chapter_number):
        return {
            "chapter_number": chapter_number,
            "source": "chapter.md",
            "checks_run": ["check_structure"],
            "counts": counts,
            "verdict": verdict,
            "findings": findings,
        }

    return _fn


def _codes(findings: list[dict]) -> set[str]:
    return {f["code"] for f in findings}


# ─── validate_plan ────────────────────────────────────────────────────


def test_validate_plan_clean():
    assert bc.validate_plan(_valid_plan(5), 5) == []


def test_validate_plan_missing_chapter_number():
    plan = _valid_plan()
    del plan["chapter_number"]
    assert "plan_missing_chapter_number" in _codes(bc.validate_plan(plan, 5))


def test_validate_plan_chapter_number_mismatch_is_warning():
    findings = bc.validate_plan(_valid_plan(4), 5)
    mism = [f for f in findings if f["code"] == "plan_chapter_number_mismatch"]
    assert len(mism) == 1
    assert mism[0]["severity"] == "warning"


def test_validate_plan_bool_chapter_number_rejected():
    # bool — подкласс int, но не валидный номер главы.
    plan = _valid_plan()
    plan["chapter_number"] = True
    assert "plan_missing_chapter_number" in _codes(bc.validate_plan(plan, 5))


def test_validate_plan_sections_not_list():
    plan = _valid_plan()
    plan["sections"] = "не список"
    assert "plan_sections_invalid" in _codes(bc.validate_plan(plan, 5))


def test_validate_plan_sections_empty():
    plan = _valid_plan()
    plan["sections"] = []
    assert "plan_sections_invalid" in _codes(bc.validate_plan(plan, 5))


def test_validate_plan_section_without_title():
    plan = _valid_plan()
    plan["sections"] = [{"number": 1, "title": "  "}]
    assert "plan_section_bad_title" in _codes(bc.validate_plan(plan, 5))


def test_validate_plan_section_without_number():
    plan = _valid_plan()
    plan["sections"] = [{"title": "Раздел без номера"}]
    assert "plan_section_bad_number" in _codes(bc.validate_plan(plan, 5))


def test_validate_plan_bridge_absent_is_warning():
    plan = _valid_plan()
    del plan["bridge_to_next"]
    findings = bc.validate_plan(plan, 5)
    bridge = [f for f in findings if f["code"] == "plan_bridge_absent"]
    assert len(bridge) == 1
    assert bridge[0]["severity"] == "warning"


def test_validate_plan_bridge_malformed_is_error():
    plan = _valid_plan()
    plan["bridge_to_next"] = {"promises": []}  # нет summary
    assert "plan_bridge_no_summary" in _codes(bc.validate_plan(plan, 5))


def test_validate_plan_bridge_promises_not_list():
    plan = _valid_plan()
    plan["bridge_to_next"] = {"summary": "ок", "promises": "строка"}
    assert "plan_bridge_no_promises" in _codes(bc.validate_plan(plan, 5))


def test_validate_plan_term_malformed():
    plan = _valid_plan()
    plan["new_terms_introduced"] = [{"term": "вектор"}]  # нет definition
    assert "plan_term_malformed" in _codes(bc.validate_plan(plan, 5))


def test_validate_plan_biohazard_malformed():
    plan = _valid_plan()
    plan["biohazards_in_chapter"] = [{"section": 2}]  # нет name
    assert "plan_biohazard_malformed" in _codes(bc.validate_plan(plan, 5))


def test_validate_plan_optional_blocks_absent_ok():
    # Без необязательных блоков (термины, биохазарды) ошибок нет.
    plan = {
        "chapter_number": 5,
        "sections": [{"number": 1, "title": "Раздел"}],
        "bridge_to_next": {"summary": "далее", "promises": []},
    }
    assert bc.validate_plan(plan, 5) == []


# ─── load_plan ────────────────────────────────────────────────────────


def test_load_plan_missing_file():
    # Каталог главы есть, но без metadata.json.
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "chapters" / "chapter_05").mkdir(parents=True)
        meta, findings = bc.load_plan(root, 5)
        assert meta is None
        assert "plan_missing_metadata" in _codes(findings)


def test_load_plan_bad_json(tmp_path: Path):
    root = _mini_repo(tmp_path, metadata=None)
    (root / "chapters" / "chapter_05" / "metadata.json").write_text(
        "{ не json", encoding="utf-8"
    )
    meta, findings = bc.load_plan(root, 5)
    assert meta is None
    assert "plan_unreadable" in _codes(findings)


def test_load_plan_not_object(tmp_path: Path):
    root = _mini_repo(tmp_path, metadata=None)
    (root / "chapters" / "chapter_05" / "metadata.json").write_text(
        "[1, 2, 3]", encoding="utf-8"
    )
    meta, findings = bc.load_plan(root, 5)
    assert meta is None
    assert "plan_not_object" in _codes(findings)


def test_load_plan_valid(tmp_path: Path):
    root = _mini_repo(tmp_path, metadata=_valid_plan(5))
    meta, findings = bc.load_plan(root, 5)
    assert isinstance(meta, dict)
    assert findings == []


# ─── run_numeric ──────────────────────────────────────────────────────


def test_run_numeric_builds_from_draft(tmp_path: Path):
    draft = "# Глава 5\n\nОпределитель: [NUMERIC: det, A=[[2,0],[1,3]]].\n"
    root = _mini_repo(tmp_path, metadata=_valid_plan(), draft=draft)
    ran, findings = bc.run_numeric(root, 5)
    assert ran is True
    assert findings == []
    chapter = (root / "chapters" / "chapter_05" / "chapter.md").read_text(
        encoding="utf-8"
    )
    assert "[NUMERIC:" not in chapter
    assert "= 6$" in chapter


def test_run_numeric_legacy_skips(tmp_path: Path):
    root = _mini_repo(
        tmp_path, metadata=_valid_plan(), chapter="# Глава 5\n\nготовая.\n"
    )
    ran, findings = bc.run_numeric(root, 5)
    assert ran is False
    assert findings == []


def test_run_numeric_marker_error_surfaced(tmp_path: Path):
    # Невырожденный синтаксис, но не квадратная матрица → ComputationError.
    draft = "# Глава 5\n\n[NUMERIC: det, A=[[1,2,3]]]\n"
    root = _mini_repo(tmp_path, metadata=_valid_plan(), draft=draft)
    ran, findings = bc.run_numeric(root, 5)
    assert ran is True
    assert "numeric_marker_error" in _codes(findings)


def test_run_numeric_no_source(tmp_path: Path):
    root = _mini_repo(tmp_path, metadata=_valid_plan())  # ни draft, ни chapter
    ran, findings = bc.run_numeric(root, 5)
    assert ran is False
    assert "numeric_no_source" in _codes(findings)


# ─── run_build (оркестратор, verify замокан) ──────────────────────────


def test_build_with_draft_runs_numeric_and_verify(tmp_path, monkeypatch):
    draft = "# Глава 5\n\n[NUMERIC: det, A=[[2,0],[1,3]]]\n"
    root = _mini_repo(tmp_path, metadata=_valid_plan(), draft=draft)
    monkeypatch.setattr(bc.verify_tools, "verify_chapter", _fake_verify("ok"))

    report = bc.run_build(root, 5)
    assert report["verdict"] == "ok"
    assert report["stages"]["numeric"]["ran"] is True
    assert "verify" in report["stages"]
    # chapter.md действительно собран.
    chapter = (root / "chapters" / "chapter_05" / "chapter.md").read_text(
        encoding="utf-8"
    )
    assert "= 6$" in chapter


def test_build_legacy_skips_numeric(tmp_path, monkeypatch):
    root = _mini_repo(
        tmp_path, metadata=_valid_plan(), chapter="# Глава 5\n\nготовая.\n"
    )
    monkeypatch.setattr(bc.verify_tools, "verify_chapter", _fake_verify("warn"))
    report = bc.run_build(root, 5)
    assert report["stages"]["numeric"]["ran"] is False
    assert report["verdict"] == "warn"


def test_build_plan_error_stops_before_numeric_and_verify(tmp_path, monkeypatch):
    bad_plan = _valid_plan()
    del bad_plan["sections"]
    root = _mini_repo(tmp_path, metadata=bad_plan, draft="# Глава 5\n")

    def _boom(root, chapter_number):  # verify не должен вызываться
        raise AssertionError("verify_chapter must not run on invalid plan")

    monkeypatch.setattr(bc.verify_tools, "verify_chapter", _boom)
    report = bc.run_build(root, 5)
    assert report["verdict"] == "fail"
    assert report["stopped_at"] == "plan"
    assert "numeric" not in report["stages"]
    assert "verify" not in report["stages"]


def test_build_numeric_error_still_verifies_and_fails(tmp_path, monkeypatch):
    draft = "# Глава 5\n\n[NUMERIC: det, A=[[1,2,3]]]\n"
    root = _mini_repo(tmp_path, metadata=_valid_plan(), draft=draft)
    calls = []

    def _spy(root, chapter_number):
        calls.append(chapter_number)
        return _fake_verify("ok")(root, chapter_number)

    monkeypatch.setattr(bc.verify_tools, "verify_chapter", _spy)
    report = bc.run_build(root, 5)
    assert report["verdict"] == "fail"  # ошибка numeric → fail
    assert calls == [5]  # verify всё равно отработал
    assert "numeric_marker_error" in _codes(report["findings"])


def test_build_no_source_is_fatal(tmp_path, monkeypatch):
    root = _mini_repo(tmp_path, metadata=_valid_plan())  # нет draft и chapter

    def _boom(root, chapter_number):
        raise AssertionError("verify must not run without a chapter source")

    monkeypatch.setattr(bc.verify_tools, "verify_chapter", _boom)
    report = bc.run_build(root, 5)
    assert report["verdict"] == "fail"
    assert report["stopped_at"] == "numeric"
    assert "numeric_no_source" in _codes(report["findings"])


def test_build_plan_warning_carries_to_verdict(tmp_path, monkeypatch):
    # Нет bridge → plan warning; verify чистый → итог warn (не fail).
    plan = _valid_plan()
    del plan["bridge_to_next"]
    root = _mini_repo(tmp_path, metadata=plan, chapter="# Глава 5\n\nготовая.\n")
    monkeypatch.setattr(bc.verify_tools, "verify_chapter", _fake_verify("ok"))
    report = bc.run_build(root, 5)
    assert report["verdict"] == "warn"
    assert "plan_bridge_absent" in _codes(report["findings"])


# ─── main / коды выхода ───────────────────────────────────────────────


def test_main_exit_code_fail(tmp_path, monkeypatch, capsys):
    root = _mini_repo(tmp_path, metadata=_valid_plan())  # no source → fail
    monkeypatch.setattr(bc.verify_tools, "verify_chapter", _fake_verify("ok"))
    rc = bc.main(["5", "--repo-root", str(root)])
    assert rc == 2
    out = capsys.readouterr().out
    assert "Итог: FAIL" in out


def test_main_json_output(tmp_path, monkeypatch, capsys):
    root = _mini_repo(
        tmp_path, metadata=_valid_plan(), chapter="# Глава 5\n\nготовая.\n"
    )
    monkeypatch.setattr(bc.verify_tools, "verify_chapter", _fake_verify("ok"))
    rc = bc.main(["5", "--repo-root", str(root), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["verdict"] == "ok"
    assert payload["chapter_number"] == 5
