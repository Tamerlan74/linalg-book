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


def _write_pattern_lib(
    tmp_path: Path,
    ids: list[str],
    *,
    conflicts_md: str | None = None,
) -> None:
    """Создать библиотеку patterns/ с файлами ids + (опц.) 00_conflicts.md."""
    pdir = tmp_path / "patterns" / "01_chapter_opening"
    pdir.mkdir(parents=True, exist_ok=True)
    for pid in ids:
        (pdir / f"{pid}.md").write_text(
            f"---\nid: {pid}\n---\n\n# Суть\n\nтело\n", encoding="utf-8"
        )
    if conflicts_md is not None:
        (tmp_path / "patterns" / "00_conflicts.md").write_text(
            conflicts_md, encoding="utf-8"
        )


# Таблица конфликтов: CONFLICT pat_a↔pat_b (раздел), REDUNDANCY pat_c↔pat_d
# (абзац). Прозаическая пометка во второй строке CONFLICT — не паттерн.
_CONFLICTS_MD = """# Конфликты

## CONFLICTS — жёсткие запреты

| Паттерн 1 | Паттерн 2 | Уровень конфликта | Объяснение |
|---|---|---|---|
| `pat_a` | `pat_b` | раздел | нельзя оба в одном разделе |
| `pat_a` | `(прямая подача нотации)` | глава | прозаическая пометка, не паттерн |

## REDUNDANCY — допустимо

| Паттерн 1 | Паттерн 2 | Уровень | Объяснение |
|---|---|---|---|
| `pat_c` | `pat_d` | абзац | переигрывание |

## SYNERGY — рекомендованные связки

`pat_a` + `pat_c` — это не таблица, парсить не нужно.
"""


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


# ─── check_terms ──────────────────────────────────────────────────────


def test_terms_clean_chapter_no_findings(tmp_path: Path) -> None:
    md = (
        "# Глава 5\n\n## 1. Раздел\n\n"
        "Вводим **[когомология]{грубо — дырки пространства}** здесь.\n"
    )
    meta = {
        "chapter_number": 5,
        "new_terms_introduced": [{"term": "когомология", "definition": "..."}],
    }
    root = _write(tmp_path, md, metadata=meta)
    assert verify_tools.check_terms(root, 5) == []


def test_terms_not_marked_is_warning(tmp_path: Path) -> None:
    # Термин в плане есть, разметки в прозе нет.
    md = "# Глава 5\n\n## 1. Раздел\n\nПросто текст про ранг без разметки.\n"
    meta = {"chapter_number": 5, "new_terms_introduced": [{"term": "ранг"}]}
    root = _write(tmp_path, md, metadata=meta)
    findings = verify_tools.check_terms(root, 5)
    nm = [f for f in findings if f["code"] == "term_not_marked"]
    assert len(nm) == 1
    assert nm[0]["severity"] == "warning"


def test_terms_unplanned_marked_is_info(tmp_path: Path) -> None:
    md = "# Глава 5\n\nВводим **[ядро]{kernel}** вне плана.\n"
    meta = {"chapter_number": 5, "new_terms_introduced": []}
    root = _write(tmp_path, md, metadata=meta)
    findings = verify_tools.check_terms(root, 5)
    up = [f for f in findings if f["code"] == "unplanned_term_marked"]
    assert len(up) == 1
    assert up[0]["severity"] == "info"


def test_terms_reintroduced_is_warning(tmp_path: Path) -> None:
    # Термин введён в главе 4, заново размечен как новый в главе 5.
    md4 = "# Глава 4\n\nВпервые: **[образ]{image}**.\n"
    md5 = "# Глава 5\n\nСнова как новый: **[образ]{image}**.\n"
    meta5 = {"chapter_number": 5, "new_terms_introduced": [{"term": "образ"}]}
    _write(tmp_path, md4, n=4)
    root = _write(tmp_path, md5, metadata=meta5, n=5)
    findings = verify_tools.check_terms(root, 5)
    ri = [f for f in findings if f["code"] == "term_reintroduced"]
    assert len(ri) == 1
    assert ri[0]["severity"] == "warning"
    # размечен и в плане → не должно быть term_not_marked
    assert "term_not_marked" not in _codes(findings)


def test_terms_missing_metadata_no_findings(tmp_path: Path) -> None:
    # Нет metadata.json → check_terms молчит (missing_metadata — забота
    # check_structure), даже если в прозе есть разметка вне плана.
    md = "# Глава 5\n\nВводим **[ядро]{kernel}**.\n"
    root = _write(tmp_path, md)
    assert verify_tools.check_terms(root, 5) == []


# ─── check_patterns ───────────────────────────────────────────────────


_PAT_MD = "# Глава 5\n\n## 1. Раздел\n\nтекст\n\n## 2. Раздел\n\nтекст\n"


def _pat_meta(sections: list[dict]) -> dict:
    return {"chapter_number": 5, "sections": sections}


def test_patterns_clean_no_findings(tmp_path: Path) -> None:
    meta = _pat_meta(
        [
            {"number": 1, "title": "Р", "patterns_used": ["pat_a"]},
            {"number": 2, "title": "Р", "patterns_used": ["pat_c"]},
        ]
    )
    root = _write(tmp_path, _PAT_MD, metadata=meta)
    _write_pattern_lib(
        tmp_path, ["pat_a", "pat_b", "pat_c", "pat_d"], conflicts_md=_CONFLICTS_MD
    )
    assert verify_tools.check_patterns(root, 5) == []


def test_patterns_unknown_is_warning(tmp_path: Path) -> None:
    meta = _pat_meta(
        [{"number": 1, "title": "Р", "patterns_used": ["pat_a", "typo_xxx"]}]
    )
    root = _write(tmp_path, _PAT_MD, metadata=meta)
    _write_pattern_lib(tmp_path, ["pat_a"], conflicts_md=_CONFLICTS_MD)
    findings = verify_tools.check_patterns(root, 5)
    unk = [f for f in findings if f["code"] == "pattern_unknown"]
    assert len(unk) == 1
    assert unk[0]["severity"] == "warning"
    assert "typo_xxx" in unk[0]["message"]


def test_patterns_conflict_same_section_is_warning(tmp_path: Path) -> None:
    # pat_a↔pat_b — CONFLICT уровня «раздел»; оба в §1.
    meta = _pat_meta([{"number": 1, "title": "Р", "patterns_used": ["pat_a", "pat_b"]}])
    root = _write(tmp_path, _PAT_MD, metadata=meta)
    _write_pattern_lib(tmp_path, ["pat_a", "pat_b"], conflicts_md=_CONFLICTS_MD)
    findings = verify_tools.check_patterns(root, 5)
    conf = [f for f in findings if f["code"] == "pattern_conflict"]
    assert len(conf) == 1
    assert conf[0]["severity"] == "warning"


def test_patterns_conflict_different_sections_no_finding(tmp_path: Path) -> None:
    # CONFLICT уровня «раздел»: pat_a в §1, pat_b в §2 → не один раздел → молчим.
    meta = _pat_meta(
        [
            {"number": 1, "title": "Р", "patterns_used": ["pat_a"]},
            {"number": 2, "title": "Р", "patterns_used": ["pat_b"]},
        ]
    )
    root = _write(tmp_path, _PAT_MD, metadata=meta)
    _write_pattern_lib(tmp_path, ["pat_a", "pat_b"], conflicts_md=_CONFLICTS_MD)
    assert "pattern_conflict" not in _codes(verify_tools.check_patterns(root, 5))


def test_patterns_chapter_level_conflict_across_sections(tmp_path: Path) -> None:
    # CONFLICT уровня «глава» срабатывает, даже если паттерны в разных разделах.
    conflicts = (
        "## CONFLICTS\n\n"
        "| Паттерн 1 | Паттерн 2 | Уровень | Объяснение |\n"
        "|---|---|---|---|\n"
        "| `pat_a` | `pat_b` | глава | нельзя в одной главе |\n"
    )
    meta = _pat_meta(
        [
            {"number": 1, "title": "Р", "patterns_used": ["pat_a"]},
            {"number": 2, "title": "Р", "patterns_used": ["pat_b"]},
        ]
    )
    root = _write(tmp_path, _PAT_MD, metadata=meta)
    _write_pattern_lib(tmp_path, ["pat_a", "pat_b"], conflicts_md=conflicts)
    conf = [
        f
        for f in verify_tools.check_patterns(root, 5)
        if f["code"] == "pattern_conflict"
    ]
    assert len(conf) == 1
    assert conf[0]["location"] is None


def test_patterns_redundancy_is_info(tmp_path: Path) -> None:
    # pat_c↔pat_d — REDUNDANCY уровня «абзац»; оба в §1.
    meta = _pat_meta([{"number": 1, "title": "Р", "patterns_used": ["pat_c", "pat_d"]}])
    root = _write(tmp_path, _PAT_MD, metadata=meta)
    _write_pattern_lib(tmp_path, ["pat_c", "pat_d"], conflicts_md=_CONFLICTS_MD)
    findings = verify_tools.check_patterns(root, 5)
    red = [f for f in findings if f["code"] == "pattern_redundancy"]
    assert len(red) == 1
    assert red[0]["severity"] == "info"


def test_parse_conflict_pairs_skips_prose_and_synergy(tmp_path: Path) -> None:
    # Прозаическая пометка (не паттерн) и блок SYNERGY не попадают в пары.
    _write_pattern_lib(tmp_path, [], conflicts_md=_CONFLICTS_MD)
    pairs = verify_tools._parse_conflict_pairs(tmp_path)
    assert {(p["p1"], p["p2"], p["relation"]) for p in pairs} == {
        ("pat_a", "pat_b", "CONFLICT"),
        ("pat_c", "pat_d", "REDUNDANCY"),
    }


def test_patterns_missing_metadata_no_findings(tmp_path: Path) -> None:
    root = _write(tmp_path, _PAT_MD)  # без metadata.json
    _write_pattern_lib(tmp_path, ["pat_a"], conflicts_md=_CONFLICTS_MD)
    assert verify_tools.check_patterns(root, 5) == []


def test_patterns_no_library_no_findings(tmp_path: Path) -> None:
    # Нет каталога patterns/ → сверять не с чем, молчим (даже при опечатке).
    meta = _pat_meta([{"number": 1, "title": "Р", "patterns_used": ["typo_xxx"]}])
    root = _write(tmp_path, _PAT_MD, metadata=meta)
    assert verify_tools.check_patterns(root, 5) == []


# ─── check_promises ───────────────────────────────────────────────────


def _ch_with_promises(promises: list[str], *, n: int = 4) -> dict:
    """metadata главы n с обещаниями в мостике."""
    return {
        "chapter_number": n,
        "bridge_to_next": {"summary": "далее", "promises": promises},
    }


def test_promises_clean_carries_all_no_findings(tmp_path: Path) -> None:
    # Глава 4 обещает 2 пункта, глава 5 подхватывает оба → молчим.
    _write(
        tmp_path, "# Глава 4\n\nтекст\n", metadata=_ch_with_promises(["a", "b"]), n=4
    )
    meta5 = {"chapter_number": 5, "previous_promises_to_fulfill": ["a", "b"]}
    root = _write(tmp_path, "# Глава 5\n\nтекст\n", metadata=meta5, n=5)
    assert verify_tools.check_promises(root, 5) == []


def test_promises_not_carried_is_warning(tmp_path: Path) -> None:
    # Глава 4 обещает, глава 5 ничего не подхватывает (пустой список).
    _write(
        tmp_path, "# Глава 4\n\nтекст\n", metadata=_ch_with_promises(["a", "b"]), n=4
    )
    meta5 = {"chapter_number": 5, "previous_promises_to_fulfill": []}
    root = _write(tmp_path, "# Глава 5\n\nтекст\n", metadata=meta5, n=5)
    findings = verify_tools.check_promises(root, 5)
    nc = [f for f in findings if f["code"] == "promises_not_carried"]
    assert len(nc) == 1
    assert nc[0]["severity"] == "warning"


def test_promises_not_carried_when_field_absent(tmp_path: Path) -> None:
    # previous_promises_to_fulfill вообще нет в metadata → тоже warning.
    _write(tmp_path, "# Глава 4\n\nтекст\n", metadata=_ch_with_promises(["a"]), n=4)
    root = _write(tmp_path, "# Глава 5\n\nтекст\n", metadata={"chapter_number": 5}, n=5)
    assert "promises_not_carried" in _codes(verify_tools.check_promises(root, 5))


def test_promises_shortfall_is_info(tmp_path: Path) -> None:
    # Обещано 2, подхвачен 1 → info.
    _write(
        tmp_path, "# Глава 4\n\nтекст\n", metadata=_ch_with_promises(["a", "b"]), n=4
    )
    meta5 = {"chapter_number": 5, "previous_promises_to_fulfill": ["a"]}
    root = _write(tmp_path, "# Глава 5\n\nтекст\n", metadata=meta5, n=5)
    findings = verify_tools.check_promises(root, 5)
    sf = [f for f in findings if f["code"] == "promise_count_shortfall"]
    assert len(sf) == 1
    assert sf[0]["severity"] == "info"


def test_promises_no_previous_chapter_no_findings(tmp_path: Path) -> None:
    # Нет главы 4 → нечего сверять.
    meta5 = {"chapter_number": 5, "previous_promises_to_fulfill": []}
    root = _write(tmp_path, "# Глава 5\n\nтекст\n", metadata=meta5, n=5)
    assert verify_tools.check_promises(root, 5) == []


def test_promises_previous_has_no_promises_no_findings(tmp_path: Path) -> None:
    # Глава 4 есть, но её мостик ничего не обещает.
    meta4 = {"chapter_number": 4, "bridge_to_next": {"summary": "далее"}}
    _write(tmp_path, "# Глава 4\n\nтекст\n", metadata=meta4, n=4)
    meta5 = {"chapter_number": 5, "previous_promises_to_fulfill": []}
    root = _write(tmp_path, "# Глава 5\n\nтекст\n", metadata=meta5, n=5)
    assert verify_tools.check_promises(root, 5) == []


def test_promises_missing_metadata_no_findings(tmp_path: Path) -> None:
    # Глава 4 обещает, но у главы 5 нет metadata.json → молчим
    # (missing_metadata — забота check_structure, дублировать не нужно).
    _write(tmp_path, "# Глава 4\n\nтекст\n", metadata=_ch_with_promises(["a"]), n=4)
    root = _write(tmp_path, "# Глава 5\n\nтекст\n", n=5)  # без metadata
    assert verify_tools.check_promises(root, 5) == []


# ─── check_styleguide ─────────────────────────────────────────────────


def test_styleguide_clean_prose_no_findings(tmp_path: Path) -> None:
    md = (
        "# Глава 5\n\n## 1. Раздел\n\n"
        "Матрица растягивает площадь. Вы помните это из главы 3.\n\n"
        "Перемножим: $2 \\cdot 3 = 6$. Размер матрицы — $m \\times n$.\n"
    )
    root = _write(tmp_path, md)
    assert verify_tools.check_styleguide(root, 5) == []


def test_styleguide_forbidden_phrase_is_warning(tmp_path: Path) -> None:
    md = "# Глава 5\n\nСледует заметить, что определитель растягивает площадь.\n"
    root = _write(tmp_path, md)
    findings = verify_tools.check_styleguide(root, 5)
    fp = [f for f in findings if f["code"] == "styleguide_forbidden_phrase"]
    assert len(fp) == 1
    assert fp[0]["severity"] == "warning"
    assert "следует заметить" in fp[0]["message"]
    assert fp[0]["location"] == "строка 3"


def test_styleguide_forbidden_phrase_case_insensitive(tmp_path: Path) -> None:
    # «Очевидно, что» с заглавной (начало предложения) — тоже ловим.
    md = "# Глава 5\n\nОчевидно, что сумма углов равна 180.\n"
    root = _write(tmp_path, md)
    assert "styleguide_forbidden_phrase" in _codes(
        verify_tools.check_styleguide(root, 5)
    )


def test_styleguide_filler_word_is_info(tmp_path: Path) -> None:
    md = "# Глава 5\n\nМатрица является линейным отображением.\n"
    root = _write(tmp_path, md)
    findings = verify_tools.check_styleguide(root, 5)
    fw = [f for f in findings if f["code"] == "styleguide_filler_word"]
    assert len(fw) == 1
    assert fw[0]["severity"] == "info"


def test_styleguide_filler_word_boundary(tmp_path: Path) -> None:
    # «являются» ловим, но не цепляем словоформы внутри других слов.
    md = "# Глава 5\n\nЭти векторы являются базисом. Появляются новые идеи.\n"
    root = _write(tmp_path, md)
    fw = [
        f
        for f in verify_tools.check_styleguide(root, 5)
        if f["code"] == "styleguide_filler_word"
    ]
    assert len(fw) == 1  # только «являются», не «Появляются»


def test_styleguide_times_between_numbers_is_warning(tmp_path: Path) -> None:
    md = "# Глава 5\n\nПеремножим: $2 \\times 3 = 6$.\n"
    root = _write(tmp_path, md)
    findings = verify_tools.check_styleguide(root, 5)
    fn = [f for f in findings if f["code"] == "styleguide_formula_notation"]
    assert len(fn) == 1
    assert fn[0]["severity"] == "warning"


def test_styleguide_times_for_dimensions_no_finding(tmp_path: Path) -> None:
    # «m \times n» (размер матрицы) — легитимно, не триггерит.
    md = "# Глава 5\n\nМатрица размера $m \\times n$ имеет $mn$ элементов.\n"
    root = _write(tmp_path, md)
    assert "styleguide_formula_notation" not in _codes(
        verify_tools.check_styleguide(root, 5)
    )


def test_styleguide_no_metadata_still_runs(tmp_path: Path) -> None:
    # check_styleguide работает по прозе и не требует metadata.json.
    md = "# Глава 5\n\nНетрудно видеть, что это так.\n"
    root = _write(tmp_path, md)  # без metadata
    assert "styleguide_forbidden_phrase" in _codes(
        verify_tools.check_styleguide(root, 5)
    )


# ─── check_links ──────────────────────────────────────────────────────


def test_links_clean_no_findings(tmp_path: Path) -> None:
    md = (
        "# Глава 5\n\n## 1. Раздел\n\n"
        "![Схема](images/diagram.svg)\n\n"
        "Мы помним это из главы 4.\n"
    )
    root = _write(tmp_path, md)
    img_dir = root / "chapters" / "chapter_05" / "images"
    img_dir.mkdir()
    (img_dir / "diagram.svg").write_text("<svg/>", encoding="utf-8")
    (root / "chapters" / "chapter_04").mkdir()  # ссылка «из главы 4» валидна
    assert verify_tools.check_links(root, 5) == []


def test_links_missing_image_is_error(tmp_path: Path) -> None:
    md = "# Глава 5\n\n![Схема](images/missing.svg)\n"
    root = _write(tmp_path, md)
    findings = verify_tools.check_links(root, 5)
    mi = [f for f in findings if f["code"] == "missing_image"]
    assert len(mi) == 1
    assert mi[0]["severity"] == "error"
    assert mi[0]["location"] == "строка 3"
    assert "images/missing.svg" in mi[0]["message"]


def test_links_existing_image_no_finding(tmp_path: Path) -> None:
    md = "# Глава 5\n\n![Схема](images/here.svg)\n"
    root = _write(tmp_path, md)
    img = root / "chapters" / "chapter_05" / "images"
    img.mkdir()
    (img / "here.svg").write_text("<svg/>", encoding="utf-8")
    assert "missing_image" not in _codes(verify_tools.check_links(root, 5))


def test_links_external_image_skipped(tmp_path: Path) -> None:
    # Внешнюю картинку офлайн не проверить — пропускаем, не ругаемся.
    md = "# Глава 5\n\n![Внешняя](https://example.com/pic.png)\n"
    root = _write(tmp_path, md)
    assert verify_tools.check_links(root, 5) == []


def test_links_broken_chapter_ref_is_warning(tmp_path: Path) -> None:
    # Глава 5 ссылается на главу 3, которой в репозитории нет.
    md = "# Глава 5\n\nКак мы выяснили в главе 3, det растягивает площадь.\n"
    root = _write(tmp_path, md)
    findings = verify_tools.check_links(root, 5)
    br = [f for f in findings if f["code"] == "broken_chapter_ref"]
    assert len(br) == 1
    assert br[0]["severity"] == "warning"
    assert "3" in br[0]["message"]


def test_links_existing_chapter_ref_no_finding(tmp_path: Path) -> None:
    md = "# Глава 5\n\nКак мы выяснили в главе 3, всё хорошо.\n"
    root = _write(tmp_path, md)
    (root / "chapters" / "chapter_03").mkdir()  # глава 3 существует
    assert "broken_chapter_ref" not in _codes(verify_tools.check_links(root, 5))


def test_links_broken_chapter_ref_dedup(tmp_path: Path) -> None:
    # Дважды упомянута глава 3 → одна находка (дедуп по номеру главы).
    md = "# Глава 5\n\nСм. главу 3 здесь.\n\nИ ещё раз из главы 3 там.\n"
    root = _write(tmp_path, md)
    br = [
        f
        for f in verify_tools.check_links(root, 5)
        if f["code"] == "broken_chapter_ref"
    ]
    assert len(br) == 1


def test_links_chapter_ref_abbrev(tmp_path: Path) -> None:
    # «гл. 7» — тоже ссылка на главу.
    md = "# Глава 5\n\nПодробности в гл. 7.\n"
    root = _write(tmp_path, md)
    br = [
        f
        for f in verify_tools.check_links(root, 5)
        if f["code"] == "broken_chapter_ref"
    ]
    assert len(br) == 1
    assert "7" in br[0]["message"]


def test_links_chapter_word_without_number_no_finding(tmp_path: Path) -> None:
    # «в этой главе» без номера — не ссылка, ничего не ловим.
    md = "# Глава 5\n\nВ этой главе мы поговорим о матрицах.\n"
    root = _write(tmp_path, md)
    assert "broken_chapter_ref" not in _codes(verify_tools.check_links(root, 5))


def test_links_no_metadata_still_runs(tmp_path: Path) -> None:
    # check_links работает по прозе + ФС, metadata.json не нужен.
    md = "# Глава 5\n\n![X](images/none.svg)\n"
    root = _write(tmp_path, md)  # без metadata
    assert "missing_image" in _codes(verify_tools.check_links(root, 5))


# ─── check_terminology (контролируемый словарь) ───────────────────────


# Словарь с одной записью: канон «определитель», запрещённый «детерминант».
_TERM_DICT = (
    "terms:\n"
    "  - canon: определитель\n"
    "    variants: [детерминант]\n"
    "    note: в книге единый термин — «определитель»\n"
)


def _write_terminology(root: Path, yaml_text: str) -> None:
    """Записать book_meta/terminology.yaml во временное репо."""
    meta = root / "book_meta"
    meta.mkdir(parents=True, exist_ok=True)
    (meta / "terminology.yaml").write_text(yaml_text, encoding="utf-8")


def test_terminology_variant_flagged(tmp_path: Path) -> None:
    root = _write(tmp_path, "# Глава 5\n\nМы считаем детерминант матрицы.\n")
    _write_terminology(root, _TERM_DICT)
    [f] = verify_tools.check_terminology(root, 5)
    assert f["code"] == "noncanonical_term"
    assert f["severity"] == "warning"
    assert "детерминант" in f["message"]
    assert "определитель" in f["message"]
    assert f["location"] == "строка 3"


def test_terminology_inflection_caught(tmp_path: Path) -> None:
    # «детерминанта» — окончание дописано к варианту, должно ловиться.
    root = _write(tmp_path, "# Глава 5\n\nЗнак детерминанта меняется.\n")
    _write_terminology(root, _TERM_DICT)
    assert "noncanonical_term" in _codes(verify_tools.check_terminology(root, 5))


def test_terminology_canon_not_flagged(tmp_path: Path) -> None:
    # Проза использует сам канон — нарушения нет.
    root = _write(tmp_path, "# Глава 5\n\nМы считаем определитель матрицы.\n")
    _write_terminology(root, _TERM_DICT)
    assert verify_tools.check_terminology(root, 5) == []


def test_terminology_case_insensitive(tmp_path: Path) -> None:
    root = _write(tmp_path, "# Глава 5\n\nДетерминант равен нулю.\n")
    _write_terminology(root, _TERM_DICT)
    assert "noncanonical_term" in _codes(verify_tools.check_terminology(root, 5))


def test_terminology_dedup_and_count(tmp_path: Path) -> None:
    # Три вхождения варианта → одна находка с числом «3×».
    md = "# Глава 5\n\nдетерминант, детерминант и ещё раз детерминант.\n"
    root = _write(tmp_path, md)
    _write_terminology(root, _TERM_DICT)
    [f] = verify_tools.check_terminology(root, 5)
    assert "3×" in f["message"]
    assert f["location"] == "строка 3"


def test_terminology_inside_math_skipped(tmp_path: Path) -> None:
    # Вариант внутри инлайн-математики не считается прозой.
    root = _write(tmp_path, "# Глава 5\n\nФормула $детерминант = 0$ дана.\n")
    _write_terminology(root, _TERM_DICT)
    assert verify_tools.check_terminology(root, 5) == []


def test_terminology_inside_code_skipped(tmp_path: Path) -> None:
    # Вариант внутри backtick-кода не считается прозой.
    root = _write(tmp_path, "# Глава 5\n\nИдентификатор `детерминант` в коде.\n")
    _write_terminology(root, _TERM_DICT)
    assert verify_tools.check_terminology(root, 5) == []


def test_terminology_note_appended(tmp_path: Path) -> None:
    root = _write(tmp_path, "# Глава 5\n\nЗдесь детерминант.\n")
    _write_terminology(root, _TERM_DICT)
    [f] = verify_tools.check_terminology(root, 5)
    assert f["message"].endswith("в книге единый термин — «определитель»")


def test_terminology_multiword_variant(tmp_path: Path) -> None:
    # Многословный вариант «собственное число» ловится точной формой.
    term_dict = (
        "terms:\n  - canon: собственное значение\n    variants: [собственное число]\n"
    )
    root = _write(tmp_path, "# Глава 5\n\nНайдём собственное число оператора.\n")
    _write_terminology(root, term_dict)
    [f] = verify_tools.check_terminology(root, 5)
    assert f["code"] == "noncanonical_term"
    assert "собственное число" in f["message"]
    assert "собственное значение" in f["message"]


def test_terminology_variant_equal_canon_ignored(tmp_path: Path) -> None:
    # Вариант, совпадающий с каноном (без учёта регистра), отбрасывается.
    _write_terminology(
        tmp_path,
        "terms:\n  - canon: определитель\n    variants: [Определитель]\n",
    )
    assert verify_tools._load_terminology(tmp_path) == []


def test_terminology_malformed_yaml_silent(tmp_path: Path) -> None:
    root = _write(tmp_path, "# Глава 5\n\nдетерминант.\n")
    _write_terminology(root, "terms: : : не yaml\n")
    assert verify_tools.check_terminology(root, 5) == []


def test_terminology_severity_off_via_config(tmp_path: Path) -> None:
    root = _write(tmp_path, "# Глава 5\n\nдетерминант.\n")
    _write_terminology(root, _TERM_DICT)
    assert _codes(verify_tools.check_terminology(root, 5)) == {"noncanonical_term"}
    _write_config(root, 'check_terminology:\n  noncanonical_term: "off"\n')
    assert verify_tools.check_terminology(root, 5) == []


def test_load_terminology_absent_returns_empty(tmp_path: Path) -> None:
    assert verify_tools._load_terminology(tmp_path) == []


def test_terminology_no_terms_key_silent(tmp_path: Path) -> None:
    # Файл есть, но без списка terms → словарь пуст, проверка молчит.
    root = _write(tmp_path, "# Глава 5\n\nдетерминант.\n")
    _write_terminology(root, "note: просто комментарий\n")
    assert verify_tools._load_terminology(root) == []
    assert verify_tools.check_terminology(root, 5) == []


# ─── verify_chapter ───────────────────────────────────────────────────


def test_verify_clean_chapter_ok(tmp_path: Path) -> None:
    root = _write(tmp_path, _CLEAN_MD, metadata=_CLEAN_META, biohazard_freq="2-3 раза")
    report = verify_tools.verify_chapter(root, 5)
    assert report["verdict"] == "ok"
    assert report["counts"] == {"error": 0, "warning": 0, "info": 0}
    assert report["checks_run"] == [
        "check_structure",
        "check_markers",
        "check_terms",
        "check_patterns",
        "check_promises",
        "check_styleguide",
        "check_links",
        "check_terminology",
    ]
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


# ─── checks_config.yaml (строгость кодов) ─────────────────────────────


# Глава с ровно одной находкой section_title_mismatch (warning): заголовок
# раздела 2 в прозе расходится с планом _CLEAN_META.
_MISMATCH_MD = _CLEAN_MD.replace("## 2. Второй раздел", "## 2. Другой заголовок")


def _write_config(root: Path, yaml_text: str) -> None:
    """Записать book_meta/checks_config.yaml во временное репо."""
    meta = root / "book_meta"
    meta.mkdir(parents=True, exist_ok=True)
    (meta / "checks_config.yaml").write_text(yaml_text, encoding="utf-8")


def test_config_absent_keeps_default_severity(tmp_path: Path) -> None:
    root = _write(tmp_path, _MISMATCH_MD, metadata=_CLEAN_META)
    [f] = verify_tools.check_structure(root, 5)
    assert f["code"] == "section_title_mismatch"
    assert f["severity"] == "warning"  # дефолт: конфига нет


def test_config_remaps_severity(tmp_path: Path) -> None:
    root = _write(tmp_path, _MISMATCH_MD, metadata=_CLEAN_META)
    _write_config(root, "check_structure:\n  section_title_mismatch: error\n")
    [f] = verify_tools.check_structure(root, 5)
    assert f["severity"] == "error"


def test_config_off_drops_finding(tmp_path: Path) -> None:
    root = _write(tmp_path, _MISMATCH_MD, metadata=_CLEAN_META)
    _write_config(root, 'check_structure:\n  section_title_mismatch: "off"\n')
    assert verify_tools.check_structure(root, 5) == []


def test_config_bare_off_is_boolean_false(tmp_path: Path) -> None:
    """Голый off YAML разбирает как False — тоже трактуем как «убрать»."""
    root = _write(tmp_path, _MISMATCH_MD, metadata=_CLEAN_META)
    _write_config(root, "check_structure:\n  section_title_mismatch: off\n")
    assert verify_tools.check_structure(root, 5) == []


def test_config_unknown_severity_ignored(tmp_path: Path) -> None:
    root = _write(tmp_path, _MISMATCH_MD, metadata=_CLEAN_META)
    _write_config(root, "check_structure:\n  section_title_mismatch: bogus\n")
    [f] = verify_tools.check_structure(root, 5)
    assert f["severity"] == "warning"  # неизвестная строгость → дефолт


def test_config_malformed_yaml_uses_defaults(tmp_path: Path) -> None:
    root = _write(tmp_path, _MISMATCH_MD, metadata=_CLEAN_META)
    _write_config(root, "check_structure: : : не yaml\n")
    [f] = verify_tools.check_structure(root, 5)
    assert f["severity"] == "warning"  # битый YAML → дефолт, без падения


def test_config_unknown_check_code_is_noop(tmp_path: Path) -> None:
    root = _write(tmp_path, _MISMATCH_MD, metadata=_CLEAN_META)
    _write_config(root, "check_nonexistent:\n  whatever: error\n")
    [f] = verify_tools.check_structure(root, 5)
    assert f["severity"] == "warning"


def test_config_section_not_dict_ignored(tmp_path: Path) -> None:
    root = _write(tmp_path, _MISMATCH_MD, metadata=_CLEAN_META)
    _write_config(root, "check_structure: error\n")  # должна быть карта код→строгость
    [f] = verify_tools.check_structure(root, 5)
    assert f["severity"] == "warning"


def test_config_off_changes_verdict_via_verify_chapter(tmp_path: Path) -> None:
    root = _write(
        tmp_path, _MISMATCH_MD, metadata=_CLEAN_META, biohazard_freq="2-3 раза"
    )
    assert verify_tools.verify_chapter(root, 5)["verdict"] == "warn"
    _write_config(root, 'check_structure:\n  section_title_mismatch: "off"\n')
    report = verify_tools.verify_chapter(root, 5)
    assert report["verdict"] == "ok"
    assert report["counts"] == {"error": 0, "warning": 0, "info": 0}


def test_load_checks_config_absent_returns_empty(tmp_path: Path) -> None:
    assert verify_tools._load_checks_config(tmp_path) == {}


def test_load_checks_config_parses_and_normalizes(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        "check_terms:\n"
        "  unplanned_term_marked: off\n"
        "check_styleguide:\n"
        '  styleguide_formula_notation: "ERROR"\n',
    )
    cfg = verify_tools._load_checks_config(tmp_path)
    assert cfg[("check_terms", "unplanned_term_marked")] == "off"
    assert cfg[("check_styleguide", "styleguide_formula_notation")] == "error"


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


def test_real_chapter4_terms_findings(real_repo: Path) -> None:
    """Глава 4: в плане 3 новых термина, в прозе разметки нет вовсе."""
    findings = verify_tools.check_terms(real_repo, 4)
    not_marked = [f for f in findings if f["code"] == "term_not_marked"]
    assert len(not_marked) == 3


def test_real_chapter4_patterns_findings(real_repo: Path) -> None:
    """Глава 4: intro_analogy_first + intro_etymology вместе в §1 → 1 redundancy."""
    findings = verify_tools.check_patterns(real_repo, 4)
    assert len(findings) == 1
    f = findings[0]
    assert f["code"] == "pattern_redundancy"
    assert f["severity"] == "info"
    assert "intro_analogy_first" in f["message"]
    assert "intro_etymology" in f["message"]


def test_real_chapter4_verdict_fail(real_repo: Path) -> None:
    report = verify_tools.verify_chapter(real_repo, 4)
    assert report["verdict"] == "fail"
    assert report["counts"]["error"] >= 1


def test_real_chapter5_promises_findings(real_repo: Path) -> None:
    """Глава 5: мостик главы 4 обещает 2 пункта, глава 5 подхватывает 1.

    Фикстур chapters/chapter_05 намеренно перечисляет одно из двух
    обещаний → ровно один promise_count_shortfall (info).
    """
    findings = verify_tools.check_promises(real_repo, 5)
    sf = [f for f in findings if f["code"] == "promise_count_shortfall"]
    assert len(sf) == 1
    assert sf[0]["severity"] == "info"


def test_real_chapter4_styleguide_clean(real_repo: Path) -> None:
    """Глава 4 написана по стилгайду: ни канцелярита, ни \\times между числами.

    Реальный смоук проверяет обратное синтетическим фикстурам — что
    хорошая проза проходит без ложных срабатываний.
    """
    assert verify_tools.check_styleguide(real_repo, 4) == []


def test_real_chapter4_links_findings(real_repo: Path) -> None:
    """Глава 4: 5 картинок images/*.svg без файлов (нет папки images/) и

    ссылка «из главы 3», для которой нет папки chapter_03 в фикстуре.
    """
    findings = verify_tools.check_links(real_repo, 4)
    missing_img = [f for f in findings if f["code"] == "missing_image"]
    broken_ref = [f for f in findings if f["code"] == "broken_chapter_ref"]
    assert len(missing_img) == 5
    assert all(f["severity"] == "error" for f in missing_img)
    assert len(broken_ref) == 1
    assert broken_ref[0]["severity"] == "warning"
    assert "3" in broken_ref[0]["message"]


def test_real_chapter4_terminology_clean(real_repo: Path) -> None:
    """Реальный словарь — пока только шаблон без активных записей.

    `book_meta/terminology.yaml` закомментирован, значит словарь пуст и
    `check_terminology` молчит для любой главы.
    """
    assert verify_tools._load_terminology(real_repo) == []
    assert verify_tools.check_terminology(real_repo, 4) == []
