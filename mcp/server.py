"""MCP-сервер linalg-book-mcp — внешнее хранилище контекста книги.

Реализована вся Группа A — предоставление контекста (Часть 0 брифинга,
§6): ``get_book_info``, ``get_style_guide``, ``get_chapter``,
``get_chapter_plan``, ``get_pending_promises``, ``get_glossary``,
``get_patterns_for_phase``, ``get_pattern_details``, ``get_conflicts_table``.
Этого достаточно, чтобы Claude в чате claude.ai получал от сервера весь
контекст книги по требованию.

Группа B (проверки готовой главы): ``check_structure``, ``check_markers``,
``check_terms``, ``check_patterns`` и оркестратор ``verify_chapter``.
Вычисления — в ``tools/verify_tools.py``. Остальные проверки добавятся
следующими срезами.

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
from tools import context_tools, verify_tools  # noqa: E402

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
    log.info(
        "tool: get_chapter(chapter_number=%s, section=%s)", chapter_number, section
    )
    return context_tools.get_chapter(REPO_ROOT, chapter_number, section)


@mcp.tool()
def get_chapter_plan(chapter_number: int) -> dict[str, Any]:
    """План главы целиком — содержимое её metadata.json.

    Используй, когда автор просит «продолжить главу N» и у главы уже есть
    начатый план (разделы, обещания, новые термины, биохазарды).

    Args:
        chapter_number: номер главы (1, 2, ...).
    """
    log.info("tool: get_chapter_plan(chapter_number=%s)", chapter_number)
    return context_tools.get_chapter_plan(REPO_ROOT, chapter_number)


@mcp.tool()
def get_pending_promises(for_chapter: int) -> list[dict[str, Any]]:
    """Обещания из мостика предыдущей главы, которые надо отработать сейчас.

    Вызывай при планировании новой главы: какие обещания (из
    «Мостика к следующей главе» предыдущей главы) она должна выполнить.

    Args:
        for_chapter: номер главы, которую планируешь писать.
    """
    log.info("tool: get_pending_promises(for_chapter=%s)", for_chapter)
    return context_tools.get_pending_promises(REPO_ROOT, for_chapter)


@mcp.tool()
def get_glossary() -> list[dict[str, Any]]:
    """Глоссарий уже введённых терминов: term, definition, introduced_in.

    Вызывай, чтобы не вводить термин повторно и использовать тот же
    вариант термина, что был в предыдущих главах. Собирается из разметки
    **[термин]{определение}** в тексте глав.
    """
    log.info("tool: get_glossary")
    return context_tools.get_glossary(REPO_ROOT)


@mcp.tool()
def get_patterns_for_phase(phase: str) -> list[dict[str, Any]]:
    """Паттерны изложения для конкретной фазы главы (краткие карточки).

    Вызывай, планируя, какие приёмы применить в очередном разделе.
    Полную инструкцию по паттерну бери через get_pattern_details(id).

    Args:
        phase: одна из фаз — global, chapter_opening, introducing_concept,
            deriving_formula, climax, biohazards, pauses, chapter_closing,
            tasks, book_level.
    """
    log.info("tool: get_patterns_for_phase(phase=%s)", phase)
    return context_tools.get_patterns_for_phase(REPO_ROOT, phase)


@mcp.tool()
def get_pattern_details(pattern_id: str) -> str:
    """Полный текст конкретного паттерна по его ID (включая инструкцию LLM).

    Вызывай, когда нужны детали применения паттерна, найденного через
    get_patterns_for_phase.

    Args:
        pattern_id: идентификатор паттерна, например "biohazard_marker".
    """
    log.info("tool: get_pattern_details(pattern_id=%s)", pattern_id)
    return context_tools.get_pattern_details(REPO_ROOT, pattern_id)


@mcp.tool()
def get_conflicts_table() -> str:
    """Таблица конфликтов между паттернами (Markdown).

    Вызывай при подборе паттернов для главы, чтобы не комбинировать
    конфликтующие приёмы.
    """
    log.info("tool: get_conflicts_table")
    return context_tools.get_conflicts_table(REPO_ROOT)


# ─── Группа B: проверки готовой главы ─────────────────────────────────


@mcp.tool()
def check_structure(chapter_number: int) -> list[dict[str, Any]]:
    """Проверить структуру главы против её плана (metadata.json).

    Сверяет прозу с планом: есть ли H1, все ли заявленные разделы на
    месте и в правильном порядке, совпадают ли заголовки, есть ли итог
    и мостик. Возвращает список находок (severity error/warning/info).

    Args:
        chapter_number: номер проверяемой главы.
    """
    log.info("tool: check_structure(chapter_number=%s)", chapter_number)
    return verify_tools.check_structure(REPO_ROOT, chapter_number)


@mcp.tool()
def check_markers(chapter_number: int) -> list[dict[str, Any]]:
    """Проверить маркеры биохазарда ⚠ в главе.

    Сверяет число ⚠ с планом (biohazards_in_chapter), частоту — с
    паттерном biohazard_marker, и стоят ли маркеры в начале блока.
    Возвращает список находок.

    Args:
        chapter_number: номер проверяемой главы.
    """
    log.info("tool: check_markers(chapter_number=%s)", chapter_number)
    return verify_tools.check_markers(REPO_ROOT, chapter_number)


@mcp.tool()
def check_terms(chapter_number: int) -> list[dict[str, Any]]:
    """Проверить термины главы против плана и глоссария.

    Сверяет термины из плана (new_terms_introduced) с разметкой
    **[термин]{определение}** в прозе и с глоссарием предыдущих глав:
    не размеченные термины, размеченные вне плана, повторный ввод уже
    введённого термина. Возвращает список находок.

    Args:
        chapter_number: номер проверяемой главы.
    """
    log.info("tool: check_terms(chapter_number=%s)", chapter_number)
    return verify_tools.check_terms(REPO_ROOT, chapter_number)


@mcp.tool()
def check_patterns(chapter_number: int) -> list[dict[str, Any]]:
    """Проверить паттерны главы против библиотеки и таблицы конфликтов.

    Сверяет patterns_used каждого раздела с библиотекой patterns/
    (неизвестные ID — опечатки) и с 00_conflicts.md: конфликтующие
    (CONFLICT) и переигрывающие (REDUNDANCY) пары паттернов в одной
    главе/разделе. Возвращает список находок.

    Args:
        chapter_number: номер проверяемой главы.
    """
    log.info("tool: check_patterns(chapter_number=%s)", chapter_number)
    return verify_tools.check_patterns(REPO_ROOT, chapter_number)


@mcp.tool()
def check_promises(chapter_number: int) -> list[dict[str, Any]]:
    """Проверить, подхватила ли глава обещания мостика предыдущей главы.

    Сверяет bridge_to_next.promises главы N−1 с previous_promises_to_fulfill
    главы N: потеряны ли обещания (ничего не подхвачено) или подхвачено
    меньше пунктов, чем обещано. Бухгалтерия смежности, без семантической
    сверки прозы. Возвращает список находок.

    Args:
        chapter_number: номер проверяемой главы.
    """
    log.info("tool: check_promises(chapter_number=%s)", chapter_number)
    return verify_tools.check_promises(REPO_ROOT, chapter_number)


@mcp.tool()
def check_styleguide(chapter_number: int) -> list[dict[str, Any]]:
    """Проверить прозу главы против механически проверяемой части стилгайда.

    Ловит запрещённые канцелярские конструкции из стоп-списка стилгайда
    (warning), связку-наполнитель «является» (info) и \\times между
    числами вместо \\cdot (warning). Семантика (залог, тон, «голая»
    математика) — вне охвата, это не для детерминированной проверки.
    Возвращает список находок.

    Args:
        chapter_number: номер проверяемой главы.
    """
    log.info("tool: check_styleguide(chapter_number=%s)", chapter_number)
    return verify_tools.check_styleguide(REPO_ROOT, chapter_number)


@mcp.tool()
def check_links(chapter_number: int) -> list[dict[str, Any]]:
    """Проверить ссылки главы против файловой системы.

    Сверяет прозу с диском: существуют ли локальные картинки
    **[alt](images/...)** (missing_image, error) и есть ли папка
    chapter_NN для каждой упомянутой «главы N» (broken_chapter_ref,
    warning; сюда же ссылки «вперёд» на ещё не написанные главы).
    Внешние ссылки (http/https/data) пропускаются. metadata.json не
    нужен — работает и на черновике. Возвращает список находок.

    Args:
        chapter_number: номер проверяемой главы.
    """
    log.info("tool: check_links(chapter_number=%s)", chapter_number)
    return verify_tools.check_links(REPO_ROOT, chapter_number)


@mcp.tool()
def verify_chapter(chapter_number: int) -> dict[str, Any]:
    """Запустить все проверки главы и вернуть сводный отчёт.

    Оркестратор: прогоняет check_structure, check_markers, check_terms,
    check_patterns, check_promises, check_styleguide и check_links,
    агрегирует находки, считает error/warning/info и выдаёт вердикт
    ok/warn/fail. Вызывай после написания черновика главы.

    Args:
        chapter_number: номер проверяемой главы.
    """
    log.info("tool: verify_chapter(chapter_number=%s)", chapter_number)
    return verify_tools.verify_chapter(REPO_ROOT, chapter_number)


# ─── Точка входа ──────────────────────────────────────────────────────
if __name__ == "__main__":
    log.info("Запускаю MCP-сервер 'linalg-book' через stdio...")
    mcp.run()  # транспорт по умолчанию — stdio
