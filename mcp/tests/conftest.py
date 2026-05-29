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
        "Вводный абзац.\n\n"
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
    return tmp_path
