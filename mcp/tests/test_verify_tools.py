"""Тесты Группы B — проверки главы (verify_tools).

Синтетические главы во временной папке покрывают каждое правило точечно;
в конце — smoke-тест против реальной главы 4, где проза намеренно
рассогласована с metadata.json (отсутствует раздел 3, расходится
заголовок раздела 5, число биохазардов не сходится).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools import verify_tools
from tools.context_tools import ContentNotFoundError

# ─── хелперы ──────────────────────────────────────────────────────────


def _write(
    tmp_path: Path,
    chapter_md: str,
    *,
    metadata: dict | None = None,
    biohazard_freq: str | None = None,
    n: int = 5,
) -> Path:
    """Собрать мини-репо: глава n + (опц.) metadata + (опц.) паттерн ⚠."""
    ch = tmp_path / "chapters" / f"chapter_{n:02d}"
    ch.mkdir(parents=True)
    (ch / "chapter.md").write_text(chapter_md, encoding="utf-8")
    if metadata is not None:
        (ch / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False), encoding="utf-8"
        )
    if biohazard_freq is not None:
        p = tmp_path / "patterns" / "05_biohazards"
        p.mkdir(parents=True)
        (p / "biohazard_marker.md").write_text(
            "---\n"
            "id: biohazard_marker\n"
            f"frequency_per_chapter: {biohazard_freq}\n"
            "---\n\n# Суть\n\nтело\n",
            encoding="utf-8",
        )
    return tmp_path


def _codes(findings: list[dict]) -> set[str]:
    return {f["code"] for f in findings}


# Чистая глава: всё совпадает с планом.
_CLEAN_MD = """# Глава 5. Тест

Преамбула.

## 1. Первый раздел

текст

## 2. Второй раздел

текст

## 3. ⚠ Биохазард: деление на ноль

текст биохазарда

## Что мы теперь знаем

итог

## Мостик к следующей главе

мостик
"""

_CLEAN_META = {
    "chapter_number": 5,
    "sections": [
        {"number": 1, "title": "Первый раздел"},
        {"number": 2, "title": "Второй раздел"},
        {"number": 3, "title": "⚠ Биохазард: деление на ноль"},
    ],
    "biohazards_in_chapter": [{"name": "деление на ноль", "section": 3}],
    "bridge_to_next": {"summary": "далее", "promises": ["обещание"]},
}


# ─── check_structure ──────────────────────────────────────────────────


def test_structure_clean_chapter_no_findings(tmp_path: Path) -> None:
    root = _write(tmp_path, _CLEAN_MD, metadata=_CLEAN_META)
    assert verify_tools.check_structure(root, 5) == []


def test_structure_missing_section_is_error(tmp_path: Path) -> None:
    # В прозе нет раздела 3, хотя план его требует.
    md = _CLEAN_MD.replace(
        "## 3. ⚠ Биохазард: деление на ноль\n\nтекст биохазарда\n\n", ""
    )
    root = _write(tmp_path, md, metadata=_CLEAN_META)
    findings = verify_tools.check_structure(root, 5)
    missing = [f for f in findings if f["code"] == "missing_section"]
    assert len(missing) == 1
    assert missing[0]["severity"] == "error"


def test_structure_title_mismatch_is_warning(tmp_path: Path) -> None:
    md = _CLEAN_MD.replace("## 2. Второй раздел", "## 2. Совсем другой заголовок")
    root = _write(tmp_path, md, metadata=_CLEAN_META)
    findings = verify_tools.check_structure(root, 5)
    mism = [f for f in findings if f["code"] == "section_title_mismatch"]
    assert len(mism) == 1
    assert mism[0]["severity"] == "warning"


def test_structure_missing_h1_is_error(tmp_path: Path) -> None:
    md = _CLEAN_MD.replace("# Глава 5. Тест\n\nПреамбула.\n\n", "Преамбула.\n\n")
    root = _write(tmp_path, md, metadata=_CLEAN_META)
    assert "missing_h1" in _codes(verify_tools.check_structure(root, 5))


def test_structure_out_of_order_is_warning(tmp_path: Path) -> None:
    # Меняем местами разделы 1 и 2 в прозе → порядок 2,1,3.
    md = """# Глава 5

## 2. Второй раздел

текст

## 1. Первый раздел

текст

## 3. ⚠ Биохазард: деление на ноль

текст

## Что мы теперь знаем

итог

## Мостик к следующей главе

мостик
"""
    root = _write(tmp_path, md, metadata=_CLEAN_META)
    assert "sections_out_of_order" in _codes(verify_tools.check_structure(root, 5))


def test_structure_duplicate_section_is_warning(tmp_path: Path) -> None:
    md = """# Глава 5

## 1. Первый раздел

текст

## 1. Первый раздел снова

текст

## Что мы теперь знаем

итог
"""
    root = _write(tmp_path, md, metadata={"chapter_number": 5})
    assert "duplicate_section" in _codes(verify_tools.check_structure(root, 5))


def test_structure_missing_summary_is_warning(tmp_path: Path) -> None:
    md = _CLEAN_MD.replace("## Что мы теперь знаем\n\nитог\n\n", "")
    root = _write(tmp_path, md, metadata=_CLEAN_META)
    assert "missing_summary" in _codes(verify_tools.check_structure(root, 5))


def test_structure_missing_bridge_is_warning(tmp_path: Path) -> None:
    md = _CLEAN_MD.replace("## Мостик к следующей главе\n\nмостик\n", "")
    root = _write(tmp_path, md, metadata=_CLEAN_META)
    assert "missing_bridge" in _codes(verify_tools.check_structure(root, 5))


def test_structure_missing_metadata_is_error(tmp_path: Path) -> None:
    root = _write(tmp_path, _CLEAN_MD)  # без metadata.json
    assert "missing_metadata" in _codes(verify_tools.check_structure(root, 5))


# ─── check_markers ────────────────────────────────────────────────────


def test_markers_clean_chapter_no_findings(tmp_path: Path) -> None:
    root = _write(tmp_path, _CLEAN_MD, metadata=_CLEAN_META, biohazard_freq="2-3 раза")
    assert verify_tools.check_markers(root, 5) == []


def test_markers_count_mismatch_is_warning(tmp_path: Path) -> None:
    # План объявляет 2 биохазарда, в прозе один маркер.
    meta = dict(_CLEAN_META)
    meta["biohazards_in_chapter"] = [{"name": "a"}, {"name": "b"}]
    root = _write(tmp_path, _CLEAN_MD, metadata=meta)
    assert "biohazard_count_mismatch" in _codes(verify_tools.check_markers(root, 5))


def test_markers_frequency_exceeded_is_warning(tmp_path: Path) -> None:
    md = "# Глава 5\n\n⚠ один\n\n⚠ два\n\n⚠ три\n\n⚠ четыре\n"
    root = _write(tmp_path, md, biohazard_freq="2-3 раза, не больше")
    findings = verify_tools.check_markers(root, 5)
    assert "marker_frequency_exceeded" in _codes(findings)
    # маркеры в начале строк → нет претензий к размещению
    assert "marker_placement" not in _codes(findings)


def test_markers_placement_mid_line_is_info(tmp_path: Path) -> None:
    md = "# Глава 5\n\nЭто важно ⚠ не перепутайте порядок.\n"
    root = _write(tmp_path, md)
    findings = verify_tools.check_markers(root, 5)
    placement = [f for f in findings if f["code"] == "marker_placement"]
    assert len(placement) == 1
    assert placement[0]["severity"] == "info"


def test_markers_in_heading_placement_ok(tmp_path: Path) -> None:
    md = "# Глава 5\n\n## 4. ⚠ Биохазард: вот так правильно\n\nтекст\n"
    root = _write(tmp_path, md)
    assert "marker_placement" not in _codes(verify_tools.check_markers(root, 5))


# ─── verify_chapter ───────────────────────────────────────────────────


def test_verify_clean_chapter_ok(tmp_path: Path) -> None:
    root = _write(tmp_path, _CLEAN_MD, metadata=_CLEAN_META, biohazard_freq="2-3 раза")
    report = verify_tools.verify_chapter(root, 5)
    assert report["verdict"] == "ok"
    assert report["counts"] == {"error": 0, "warning": 0, "info": 0}
    assert report["checks_run"] == ["check_structure", "check_markers"]
    assert report["source"] == "chapter.md"


def test_verify_warn_when_only_warnings(tmp_path: Path) -> None:
    md = _CLEAN_MD.replace("## 2. Второй раздел", "## 2. Другой заголовок")
    root = _write(tmp_path, md, metadata=_CLEAN_META, biohazard_freq="2-3 раза")
    report = verify_tools.verify_chapter(root, 5)
    assert report["verdict"] == "warn"
    assert report["counts"]["error"] == 0
    assert report["counts"]["warning"] >= 1


def test_verify_fail_when_error_present(tmp_path: Path) -> None:
    md = _CLEAN_MD.replace(
        "## 3. ⚠ Биохазард: деление на ноль\n\nтекст биохазарда\n\n", ""
    )
    root = _write(tmp_path, md, metadata=_CLEAN_META)
    report = verify_tools.verify_chapter(root, 5)
    assert report["verdict"] == "fail"
    assert report["counts"]["error"] >= 1


def test_verify_missing_chapter_raises(tmp_path: Path) -> None:
    (tmp_path / "chapters").mkdir()
    with pytest.raises(ContentNotFoundError):
        verify_tools.verify_chapter(tmp_path, 5)


# ─── smoke против реального контента (глава 4) ────────────────────────


def test_real_chapter4_structure_findings(real_repo: Path) -> None:
    """Глава 4: проза опускает раздел 3 и расходится заголовком раздела 5."""
    codes = _codes(verify_tools.check_structure(real_repo, 4))
    assert "missing_section" in codes
    assert "section_title_mismatch" in codes


def test_real_chapter4_markers_findings(real_repo: Path) -> None:
    """Глава 4: в плане 2 биохазарда, в прозе один маркер ⚠."""
    codes = _codes(verify_tools.check_markers(real_repo, 4))
    assert "biohazard_count_mismatch" in codes


def test_real_chapter4_verdict_fail(real_repo: Path) -> None:
    report = verify_tools.verify_chapter(real_repo, 4)
    assert report["verdict"] == "fail"
    assert report["counts"]["error"] >= 1
