"""Тесты функций Группы A (context_tools).

Большинство тестов гоняются на программном мини-репо (фикстура
``book_repo``). Несколько smoke-тестов — на реальном репозитории, чтобы
поймать поломку настоящего book_info.yaml, глоссария и библиотеки
паттернов. Реальных глав в репозитории сейчас нет.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools import context_tools
from tools.context_tools import ContentNotFoundError, ContextToolError

# ─── get_book_info ────────────────────────────────────────────────────


def test_get_book_info_returns_dict(book_repo: Path) -> None:
    info = context_tools.get_book_info(book_repo)
    assert info["title"] == "Тестовая книга"
    assert info["total_chapters_written"] == 5
    assert info["chapters_summary"][0]["number"] == 1


def test_get_book_info_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(ContentNotFoundError):
        context_tools.get_book_info(tmp_path)


def test_get_book_info_invalid_yaml(tmp_path: Path) -> None:
    bm = tmp_path / "book_meta"
    bm.mkdir()
    # Невалидный YAML: незакрытая скобка.
    (bm / "book_info.yaml").write_text("title: [unclosed\n", encoding="utf-8")
    with pytest.raises(ContextToolError):
        context_tools.get_book_info(tmp_path)


def test_get_book_info_non_dict_raises(tmp_path: Path) -> None:
    bm = tmp_path / "book_meta"
    bm.mkdir()
    (bm / "book_info.yaml").write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(ContextToolError):
        context_tools.get_book_info(tmp_path)


# ─── get_style_guide ──────────────────────────────────────────────────


def test_get_style_guide_returns_text(book_repo: Path) -> None:
    text = context_tools.get_style_guide(book_repo)
    assert "Стилгайд" in text
    assert "«вы»" in text


def test_get_style_guide_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(ContentNotFoundError):
        context_tools.get_style_guide(tmp_path)


# ─── get_chapter ──────────────────────────────────────────────────────


def test_get_chapter_all(book_repo: Path) -> None:
    ch = context_tools.get_chapter(book_repo, 5, "all")
    assert ch["chapter_number"] == 5
    assert ch["source"] == "chapter.md"
    assert ch["section"] == "all"
    assert ch["title"] == "Глава 5. Обратная матрица"
    assert "Откат преобразования" in ch["content"]
    assert "Мостик" in ch["content"]


def test_get_chapter_prefers_chapter_over_draft(tmp_path: Path) -> None:
    d = tmp_path / "chapters" / "chapter_07"
    d.mkdir(parents=True)
    (d / "draft.md").write_text("# Черновик\n", encoding="utf-8")
    (d / "chapter.md").write_text("# Финал\n", encoding="utf-8")
    ch = context_tools.get_chapter(tmp_path, 7)
    assert ch["source"] == "chapter.md"
    assert ch["title"] == "Финал"


def test_get_chapter_falls_back_to_draft(tmp_path: Path) -> None:
    d = tmp_path / "chapters" / "chapter_08"
    d.mkdir(parents=True)
    (d / "draft.md").write_text("# Только черновик\n", encoding="utf-8")
    ch = context_tools.get_chapter(tmp_path, 8)
    assert ch["source"] == "draft.md"


def test_get_chapter_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(ContentNotFoundError):
        context_tools.get_chapter(tmp_path, 99)


def test_get_chapter_section_summary(book_repo: Path) -> None:
    ch = context_tools.get_chapter(book_repo, 5, "summary")
    assert "Что мы теперь знаем" in ch["content"]
    assert "Сводка главы" in ch["content"]
    # Не должно быть текста других разделов.
    assert "Откат преобразования" not in ch["content"]


def test_get_chapter_section_bridge(book_repo: Path) -> None:
    ch = context_tools.get_chapter(book_repo, 5, "bridge")
    assert "Мостик" in ch["content"]
    assert "Обещание следующей главы" in ch["content"]


def test_get_chapter_section_by_number(book_repo: Path) -> None:
    ch = context_tools.get_chapter(book_repo, 5, "1")
    assert "Откат преобразования" in ch["content"]
    assert "Текст раздела 1" in ch["content"]


def test_get_chapter_section_by_number_with_marker(book_repo: Path) -> None:
    # Раздел 4 в заголовке начинается с "4. ⚠ Биохазард..." — номер
    # должен находиться даже при наличии маркера.
    ch = context_tools.get_chapter(book_repo, 5, "4")
    assert "Биохазард" in ch["content"]


def test_get_chapter_section_not_found_raises(book_repo: Path) -> None:
    with pytest.raises(ContentNotFoundError):
        context_tools.get_chapter(book_repo, 5, "99")


# ─── get_chapter_plan ─────────────────────────────────────────────────


def test_get_chapter_plan_returns_dict(book_repo: Path) -> None:
    plan = context_tools.get_chapter_plan(book_repo, 5)
    assert plan["chapter_number"] == 5
    assert plan["chapter_title"] == "Обратная матрица"


def test_get_chapter_plan_missing_raises(book_repo: Path) -> None:
    with pytest.raises(ContentNotFoundError):
        context_tools.get_chapter_plan(book_repo, 99)


def test_get_chapter_plan_invalid_json_raises(tmp_path: Path) -> None:
    d = tmp_path / "chapters" / "chapter_07"
    d.mkdir(parents=True)
    (d / "metadata.json").write_text("{not valid json", encoding="utf-8")
    with pytest.raises(ContextToolError):
        context_tools.get_chapter_plan(tmp_path, 7)


# ─── get_pending_promises ─────────────────────────────────────────────


def test_get_pending_promises_for_chapter_5(book_repo: Path) -> None:
    promises = context_tools.get_pending_promises(book_repo, 5)
    assert len(promises) == 2
    first = promises[0]
    assert first["made_in_chapter"] == 4
    assert first["due_in_chapter"] == 5
    assert first["section_of_origin"] == "bridge_to_next"
    assert "обратная матрица" in first["promise"]


def test_get_pending_promises_none_for_chapter_1(book_repo: Path) -> None:
    # Для главы 1 нет «предыдущей» главы 0 — обещаний нет.
    assert context_tools.get_pending_promises(book_repo, 1) == []


def test_get_pending_promises_empty_repo(tmp_path: Path) -> None:
    assert context_tools.get_pending_promises(tmp_path, 5) == []


# ─── get_glossary ─────────────────────────────────────────────────────


def test_get_glossary_extracts_term(book_repo: Path) -> None:
    glossary = context_tools.get_glossary(book_repo)
    assert glossary == [
        {
            "term": "обратная матрица",
            "definition": "матрица, откатывающая преобразование",
            "introduced_in": 5,
        }
    ]


def test_get_glossary_first_appearance_wins(tmp_path: Path) -> None:
    # Один и тот же термин в главах 2 и 3 — фиксируется глава 2.
    for n, defn in ((3, "из главы 3"), (2, "из главы 2")):
        d = tmp_path / "chapters" / f"chapter_{n:02d}"
        d.mkdir(parents=True)
        (d / "chapter.md").write_text(
            f"# Глава {n}\n\nТекст **[ранг]{{{defn}}}** дальше.\n",
            encoding="utf-8",
        )
    glossary = context_tools.get_glossary(tmp_path)
    assert len(glossary) == 1
    assert glossary[0]["introduced_in"] == 2
    assert glossary[0]["definition"] == "из главы 2"


def test_get_glossary_empty_repo(tmp_path: Path) -> None:
    assert context_tools.get_glossary(tmp_path) == []


# ─── get_patterns_for_phase ───────────────────────────────────────────


def test_get_patterns_for_phase_returns_list(book_repo: Path) -> None:
    patterns = context_tools.get_patterns_for_phase(book_repo, "chapter_opening")
    assert len(patterns) == 1
    p = patterns[0]
    assert p["id"] == "open_self_deprecation"
    assert p["russian_name"] == "Самоуничижение автора"
    assert p["task_type"] == "reduce_anxiety"
    assert p["frequency"] == "1-2 раза на главу"
    assert p["when_to_apply"]
    assert p["when_not_to_apply"]
    assert p["example"]


def test_get_patterns_for_phase_unknown_phase_raises(book_repo: Path) -> None:
    with pytest.raises(ContextToolError):
        context_tools.get_patterns_for_phase(book_repo, "nonexistent_phase")


def test_get_patterns_for_phase_absent_dir_returns_empty(book_repo: Path) -> None:
    # Фаза валидна, но папки patterns/08_tasks/ в фикстуре нет.
    assert context_tools.get_patterns_for_phase(book_repo, "tasks") == []


def test_get_patterns_for_phase_body_and_alias_fallback(tmp_path: Path) -> None:
    """Поля берутся из тела и из ключей-синонимов, когда нет прямых.

    Эмулируем «старый» формат паттерна из реального репо: ``category``
    вместо ``task_type``, ``frequency_per_chapter`` вместо ``frequency``,
    а ``summary`` / ``when_to_apply`` / ``when_not_to_apply`` / ``example``
    лежат не во фронтматтере, а в H1-разделах тела (``# Суть`` и т. п.).
    """
    d = tmp_path / "patterns" / "02_introducing_concept"
    d.mkdir(parents=True)
    (d / "intro_legacy.md").write_text(
        "---\n"
        "id: T7\n"
        "russian_name: Аналогия прежде символов\n"
        "category: text_pattern\n"
        "frequency_per_chapter: 1-2 раза\n"
        "---\n\n"
        "# Суть\n\n"
        "Сначала простая аналогия, потом формула.\n\n"
        "# Когда применять\n\n"
        "При первом вводе абстрактного понятия.\n\n"
        "# Когда не применять\n\n"
        "В чисто справочном разделе.\n\n"
        "# Пример из главы 3\n\n"
        "«Вектор — как стрелка из начала координат».\n",
        encoding="utf-8",
    )
    patterns = context_tools.get_patterns_for_phase(tmp_path, "introducing_concept")
    assert len(patterns) == 1
    p = patterns[0]
    # id берётся из фронтматтера (даже если это «старый» код).
    assert p["id"] == "T7"
    # task_type ← category, frequency ← frequency_per_chapter.
    assert p["task_type"] == "text_pattern"
    assert p["frequency"] == "1-2 раза"
    # summary / when_* / example извлечены из тела (H1-разделов).
    assert "простая аналогия" in p["summary"]
    assert "первом вводе" in p["when_to_apply"]
    assert "справочном" in p["when_not_to_apply"]
    assert "стрелка" in p["example"]


def test_extract_h1_section_ignores_code_fence_headers() -> None:
    """H1 внутри ```-блока не считается заголовком раздела."""
    body = (
        "# Суть\n\n"
        "Текст сути.\n\n"
        "```\n"
        "# это комментарий в коде, не заголовок\n"
        "```\n\n"
        "ещё текст сути.\n\n"
        "# Когда применять\n\n"
        "Тело.\n"
    )
    summary = context_tools._extract_h1_section(body, "Суть")
    assert summary is not None
    assert "Текст сути" in summary
    assert "ещё текст сути" in summary
    assert "комментарий в коде" in summary  # код внутри раздела сохранён
    assert "Тело" not in summary  # следующий H1 не попал


# ─── get_pattern_details ──────────────────────────────────────────────


def test_get_pattern_details_by_filename(book_repo: Path) -> None:
    text = context_tools.get_pattern_details(book_repo, "open_self_deprecation")
    assert "Инструкция для LLM" in text
    assert "Самоуничижение автора как уравнитель" in text


def test_get_pattern_details_by_frontmatter_id(book_repo: Path) -> None:
    # Файл называется bio_marker_file.md, но id == biohazard_marker.
    text = context_tools.get_pattern_details(book_repo, "biohazard_marker")
    assert "Тело паттерна биохазарда" in text


def test_get_pattern_details_not_found_raises(book_repo: Path) -> None:
    with pytest.raises(ContentNotFoundError):
        context_tools.get_pattern_details(book_repo, "no_such_pattern")


def test_get_pattern_details_no_patterns_dir_raises(tmp_path: Path) -> None:
    with pytest.raises(ContentNotFoundError):
        context_tools.get_pattern_details(tmp_path, "anything")


# ─── get_conflicts_table ──────────────────────────────────────────────


def test_get_conflicts_table_returns_markdown(book_repo: Path) -> None:
    table = context_tools.get_conflicts_table(book_repo)
    assert "Конфликты паттернов" in table
    assert "open_self_deprecation" in table


def test_get_conflicts_table_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(ContentNotFoundError):
        context_tools.get_conflicts_table(tmp_path)


# ─── smoke на реальном репозитории ────────────────────────────────────


def test_real_book_info_parses(real_repo: Path) -> None:
    """Настоящий book_meta/book_info.yaml валиден и читается."""
    info = context_tools.get_book_info(real_repo)
    assert info["title"] == "Линейная алгебра, по-человечески"
    assert info["total_chapters_written"] == 0  # глав ещё нет; summary — плановый outline
    assert len(info["chapters_summary"]) == 4


def test_real_glossary_is_list(real_repo: Path) -> None:
    """get_glossary отрабатывает на реальном репо и возвращает список.

    Разметки терминов в готовых главах пока может не быть — проверяем
    лишь, что функция не падает и тип результата верный.
    """
    glossary = context_tools.get_glossary(real_repo)
    assert isinstance(glossary, list)


def test_real_patterns_chapter_opening(real_repo: Path) -> None:
    """Реальные паттерны фазы открытия читаются и карточки заполнены.

    В репо 6 паттернов открытия. У каждого должны быть id и russian_name;
    summary должен извлекаться у всех (из ``# Суть`` или ``# Описание``),
    а task_type — хотя бы у большинства (фронтматтер ``task_type`` или
    fallback на ``category``).
    """
    patterns = context_tools.get_patterns_for_phase(real_repo, "chapter_opening")
    assert len(patterns) == 6
    for p in patterns:
        assert p["id"]
        assert p["russian_name"]
        assert p["summary"], f"нет summary у {p['id']}"
    assert all(p["task_type"] for p in patterns)


def test_real_pattern_details_biohazard_by_name(real_repo: Path) -> None:
    """biohazard_marker находится по имени файла (== id после нормализации)."""
    by_name = context_tools.get_pattern_details(real_repo, "biohazard_marker")
    assert "Биохазард" in by_name


def test_real_conflicts_table_parses(real_repo: Path) -> None:
    """Таблица конфликтов читается и упоминает паттерны по имени файла."""
    table = context_tools.get_conflicts_table(real_repo)
    assert "CONFLICT" in table
    assert "open_self_deprecation" in table
