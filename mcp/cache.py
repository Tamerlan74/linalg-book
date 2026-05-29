"""In-memory кеш чтений файлов для MCP-сервера (Часть 0 брифинга, §9).

Файлы репозитория меняются редко, но Claude в чате может вызывать
``get_pattern_details`` / ``get_chapter`` много раз за сеанс. Кеш
избавляет от повторного чтения одного и того же файла.

Стратегия: словарь ``{path: (mtime, content)}``. Перед возвратом из кеша
сверяем ``mtime`` файла — если файл изменился, перечитываем. Так автор
может править контент во время сеанса, и сервер увидит свежую версию без
перезапуска.

Все чтения — строго UTF-8 (Windows по умолчанию cp1251, что ломает
кириллицу; см. Часть 1 брифинга, §7).
"""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger("linalg-book-mcp.cache")

# path (resolved, str) -> (mtime_ns, content)
_text_cache: dict[str, tuple[int, str]] = {}


def read_text(path: Path) -> str:
    """Прочитать текстовый файл (UTF-8) с mtime-кешем.

    Args:
        path: путь к файлу.

    Returns:
        Содержимое файла.

    Raises:
        FileNotFoundError: если файла нет (передаётся вызывающему — он
            решает, ошибка это или штатное отсутствие).
    """
    resolved = path.resolve()
    key = str(resolved)
    mtime = resolved.stat().st_mtime_ns  # бросит FileNotFoundError если нет

    cached = _text_cache.get(key)
    if cached is not None and cached[0] == mtime:
        log.debug("cache hit: %s", key)
        return cached[1]

    log.debug("cache miss: %s", key)
    content = resolved.read_text(encoding="utf-8")
    _text_cache[key] = (mtime, content)
    return content


def clear() -> None:
    """Очистить кеш целиком. Полезно в тестах."""
    _text_cache.clear()
