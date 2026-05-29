"""MCP-сервер linalg-book-mcp — внешнее хранилище контекста книги.

Каркас + три базовые функции Группы A (Часть 0 брифинга, §17):
``get_book_info``, ``get_style_guide``, ``get_chapter``. Этого достаточно,
чтобы автор проверил: Claude в чате claude.ai реально видит сервер и
получает от него данные книги.

Архитектура:
- Используется **FastMCP** (высокоуровневый API SDK), как в рабочем
  starter-mcp автора: ``@mcp.tool()`` генерирует схему инструмента из
  type-hints + docstring.
- Сами вычисления — в ``tools/context_tools.py`` (чистые функции,
  принимают корень репозитория). Здесь — только тонкие обёртки.
- Корень репозитория определяется в ``config.get_repo_root()``.

Запуск — через stdio (Claude Desktop / Claude Code). Все логи строго в
stderr: stdout зарезервирован под MCP-протокол.

ВАЖНО про имя пакета: папка называется ``mcp/``, что совпадает с именем
SDK-пакета ``mcp``. Чтобы ``from mcp.server.fastmcp import FastMCP``
резолвился в установленный SDK, а не в эту папку, ``mcp/`` НЕ является
пакетом (нет ``__init__.py``), а свою директорию мы добавляем в sys.path
для импорта локальных модулей (config, cache, tools).
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

# Локальные модули (config, cache, tools) лежат рядом с этим файлом.
# Добавляем директорию server.py в sys.path, чтобы их импортировать как
# top-level. Это не мешает `import mcp` найти SDK: в нашей директории нет
# подпапки/файла с именем `mcp`.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcp.server.fastmcp import FastMCP  # noqa: E402  (после sys.path)

import config  # noqa: E402
from tools import context_tools  # noqa: E402

# ─── Логирование строго в stderr ──────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("linalg-book-mcp")

REPO_ROOT = config.get_repo_root()
log.info("linalg-book-mcp: REPO_ROOT = %s", REPO_ROOT)

mcp = FastMCP("linalg-book")


# ─── Группа A: предоставление контекста ───────────────────────────────


@mcp.tool()
def get_book_info() -> dict[str, Any]:
    """Общая информация о книге: название, аудитория, стиль, список глав.

    Вызывай в начале чата, чтобы понять, с какой книгой работаешь и какие
    главы уже написаны.
    """
    log.info("tool: get_book_info")
    return context_tools.get_book_info(REPO_ROOT)


@mcp.tool()
def get_style_guide() -> str:
    """Полный текст стилгайда книги (правила тона, формул, форматирования).

    Вызывай перед написанием главы, чтобы соблюсти стиль: обращение «вы»,
    короткие предложения, активный залог, форматы формул и так далее.
    """
    log.info("tool: get_style_guide")
    return context_tools.get_style_guide(REPO_ROOT)


@mcp.tool()
def get_chapter(chapter_number: int, section: str = "all") -> dict[str, Any]:
    """Содержание написанной главы или её части — для согласованности.

    Используй, чтобы свериться с предыдущими главами: терминология,
    цитирование, что уже было сказано.

    Args:
        chapter_number: номер главы (1, 2, ...).
        section: "all" (вся глава, по умолчанию), "summary" (раздел
            «Что мы теперь знаем»), "bridge" (раздел «Мостик к следующей
            главе»), либо номер раздела как строка ("1", "4").
    """
    log.info("tool: get_chapter(chapter_number=%s, section=%s)", chapter_number, section)
    return context_tools.get_chapter(REPO_ROOT, chapter_number, section)


# ─── Точка входа ──────────────────────────────────────────────────────
if __name__ == "__main__":
    log.info("Запускаю MCP-сервер 'linalg-book' через stdio...")
    mcp.run()  # транспорт по умолчанию — stdio
