"""Тесты функций Группы A (context_tools).

Большинство тестов гоняются на программном мини-репо (фикстура
``book_repo``). Два smoke-теста — на реальном репозитории, чтобы поймать
поломку настоящего book_info.yaml / chapter_04.
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


# ─── smoke на реальном репозитории ────────────────────────────────────


def test_real_book_info_parses(real_repo: Path) -> None:
    """Настоящий book_meta/book_info.yaml валиден и читается."""
    info = context_tools.get_book_info(real_repo)
    assert info["title"] == "Линейная алгебра, по-человечески"
    assert info["total_chapters_written"] == 4
    assert len(info["chapters_summary"]) == 4


def test_real_chapter_04_parses(real_repo: Path) -> None:
    """Настоящая глава 4 читается, заголовок и разделы на месте."""
    ch = context_tools.get_chapter(real_repo, 4, "all")
    assert ch["source"] == "chapter.md"
    assert "Умножение матриц" in ch["title"]
    bridge = context_tools.get_chapter(real_repo, 4, "bridge")
    assert "обратной матрице" in bridge["content"].lower()
