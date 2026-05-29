"""Конфигурация MCP-сервера linalg-book-mcp.

Единственная задача модуля — определить **корень репозитория книги**,
от которого все остальные функции отсчитывают пути к контенту
(book_meta/, chapters/, patterns/).

Корень определяется двумя способами, в порядке приоритета:

1. Переменная окружения ``LINALG_BOOK_ROOT`` — если задана, берётся она.
   Это нужно, чтобы Claude Desktop мог указать корень явно в конфиге, не
   завися от расположения server.py.
2. Иначе — родитель папки ``mcp/`` (этот файл лежит в ``<repo>/mcp/``,
   значит ``<repo>`` = parent.parent от config.py).

Так сервер работает и при запуске из любого каталога (Claude Desktop
запускает python с абсолютным путём к server.py), и при override через env.
"""

from __future__ import annotations

import os
from pathlib import Path

# config.py лежит в <repo>/mcp/config.py → корень репозитория на два
# уровня выше этого файла.
_DEFAULT_ROOT = Path(__file__).resolve().parent.parent


def get_repo_root() -> Path:
    """Вернуть корень репозитория linalg-book.

    Returns:
        Абсолютный путь к корню. Из env ``LINALG_BOOK_ROOT`` если задан,
        иначе — родитель папки ``mcp/``.

    Note:
        Не проверяет существование подпапок (book_meta/, chapters/) —
        это ответственность конкретных функций, которые дают понятную
        ошибку, если контента ещё нет.
    """
    env_root = os.environ.get("LINALG_BOOK_ROOT")
    if env_root:
        return Path(env_root).resolve()
    return _DEFAULT_ROOT


# Имена подпапок контента — в одном месте, чтобы не плодить строковые
# литералы по всему коду.
BOOK_META_DIR = "book_meta"
CHAPTERS_DIR = "chapters"
PATTERNS_DIR = "patterns"
