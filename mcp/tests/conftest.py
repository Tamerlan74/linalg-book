"""Общая настройка pytest для тестов MCP-сервера.

Две задачи:
1. Добавить ``mcp/`` в sys.path, чтобы тесты могли импортировать
   локальные модули (``cache``, ``tools.context_tools``) так же, как это
   делает ``server.py``. Папка ``mcp/`` не пакет (совпадает с именем SDK),
   поэтому путь добавляем явно.
2. Дать фикстуры: ``book_repo`` (программно собранное мини-репо во
   временной папке) и ``real_repo`` (реальный корень репозитория — для
   smoke-проверки, что настоящий контент парсится).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# mcp/ — родитель папки tests/.
_MCP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_MCP_DIR))

# Корень репозитория — родитель mcp/.
_REPO_ROOT = _MCP_DIR.parent

import cache  # noqa: E402  (после правки sys.path)


@pytest.fixture(autouse=True)
def _clear_cache():
    """Каждый тест — с чистым кешем чтений (изоляция)."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def real_repo() -> Path:
    """Реальный корень репозитория linalg-book."""
    return _REPO_ROOT


@pytest.fixture
def book_repo(tmp_path: Path) -> Path:
    """Собрать минимальное мини-репо во временной папке.

    Структура:
        book_meta/book_info.yaml
        book_meta/style_guide.md
        chapters/chapter_05/chapter.md   (корректная глава 5)

    Возвращает корень этого мини-репо.
    """
    book_meta = tmp_path / "book_meta"
    book_meta.mkdir()
    (book_meta / "book_info.yaml").write_text(
        "title: Тестовая книга\n"
        "audience: тестовый читатель\n"
        "style: тестовый стиль\n"
        "total_chapters_written: 5\n"
        "chapters_summary:\n"
        "  - number: 1\n"
        "    title: Первая\n"
        "    key_concepts: [вектор]\n",
        encoding="utf-8",
    )
    (book_meta / "style_guide.md").write_text(
        "# Стилгайд\n\nОбращение на «вы». Короткие предложения.\n",
        encoding="utf-8",
    )

    ch05 = tmp_path / "chapters" / "chapter_05"
    ch05.mkdir(parents=True)
    (ch05 / "chapter.md").write_text(
        "# Глава 5. Обратная матрица\n\n"
        "Вводный абзац про "
        "**[обратная матрица]{матрица, откатывающая преобразование}**.\n\n"
        "## 1. Откат преобразования\n\n"
        "Текст раздела 1.\n\n"
        "## 4. ⚠ Биохазард: вырожденность\n\n"
        "Текст биохазарда.\n\n"
        "## Что мы теперь знаем\n\n"
        "Сводка главы.\n\n"
        "## Мостик к следующей главе\n\n"
        "Обещание следующей главы.\n",
        encoding="utf-8",
    )

    # metadata.json главы 5 — план главы (для get_chapter_plan).
    (ch05 / "metadata.json").write_text(
        json.dumps(
            {"chapter_number": 5, "chapter_title": "Обратная матрица"},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    # metadata.json главы 4 — мостик с обещаниями (для get_pending_promises).
    # У главы 4 здесь нет chapter.md/draft.md — только метаданные.
    ch04 = tmp_path / "chapters" / "chapter_04"
    ch04.mkdir(parents=True)
    (ch04 / "metadata.json").write_text(
        json.dumps(
            {
                "chapter_number": 4,
                "chapter_title": "Умножение матриц",
                "bridge_to_next": {
                    "summary": "можно ли матрицу разделить на матрицу?",
                    "promises": [
                        "обратная матрица как способ откатить преобразование",
                        "связь с системами линейных уравнений Mx = b",
                    ],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    # patterns/ — для get_patterns_for_phase / get_pattern_details /
    # get_conflicts_table.
    p_open = tmp_path / "patterns" / "01_chapter_opening"
    p_open.mkdir(parents=True)
    (p_open / "open_self_deprecation.md").write_text(
        "---\n"
        "id: open_self_deprecation\n"
        "russian_name: Самоуничижение автора\n"
        "task_type: reduce_anxiety\n"
        "frequency: 1-2 раза на главу\n"
        "summary: Автор признаётся, что сам когда-то не понимал.\n"
        "when_to_apply: В начале трудной темы.\n"
        "when_not_to_apply: В справочном разделе.\n"
        "example: «Я сам полгода не понимал, что такое ранг».\n"
        "---\n\n"
        "# Самоуничижение автора как уравнитель\n\n"
        "Тело паттерна.\n\n"
        "## Инструкция для LLM\n\n"
        "Применяй один раз на главу.\n",
        encoding="utf-8",
    )

    p_bio = tmp_path / "patterns" / "05_biohazards"
    p_bio.mkdir(parents=True)
    # id во фронтматтере намеренно отличается от имени файла — проверяем,
    # что get_pattern_details находит паттерн и по полю id.
    (p_bio / "bio_marker_file.md").write_text(
        "---\n"
        "id: biohazard_marker\n"
        "russian_name: Маркер биохазарда\n"
        "task_type: warn_pitfall\n"
        "---\n\n"
        "# Биохазард\n\nТело паттерна биохазарда.\n",
        encoding="utf-8",
    )

    (tmp_path / "patterns" / "00_conflicts.md").write_text(
        "# Конфликты паттернов\n\n"
        "| Паттерн A | Паттерн B | Почему конфликт |\n"
        "|---|---|---|\n"
        "| open_story_first | open_self_deprecation | оба в открытии |\n",
        encoding="utf-8",
    )
    return tmp_path
