"""Группа A — предоставление контекста (Часть 0 брифинга, §6).

Функции, отдающие Claude в чате контекст книги *до и во время* написания
главы. Все они **детерминированы**, читают только файлы репозитория,
ничего не генерируют.

Реализована вся Группа A (брифинг §6):
- :func:`get_book_info`          — общая информация о книге.
- :func:`get_style_guide`        — полный текст стилгайда.
- :func:`get_chapter`            — содержание главы (или её части).
- :func:`get_chapter_plan`       — план главы (metadata.json целиком).
- :func:`get_pending_promises`   — обещания, висящие на конкретной главе.
- :func:`get_glossary`           — термины из разметки глав.
- :func:`get_patterns_for_phase` — паттерны изложения для фазы главы.
- :func:`get_pattern_details`    — полный текст конкретного паттерна.
- :func:`get_conflicts_table`    — таблица конфликтов паттернов.

Каждая функция принимает ``root: Path`` — корень репозитория. Это делает
их тестируемыми без MCP и без переменных окружения: тест передаёт
``tmp_path``-фикстуру.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import yaml

import cache

log = logging.getLogger("linalg-book-mcp.context_tools")

# Имена подпапок дублируем сюда из config, чтобы context_tools не зависел
# от config (config — про определение корня, это забота server.py).
_BOOK_META = "book_meta"
_CHAPTERS = "chapters"
_PATTERNS = "patterns"

# Имя фазы (параметр get_patterns_for_phase) → имя подпапки в patterns/.
# Подпапки нумерованы для порядка в файловой системе; API оперирует
# «чистыми» именами фаз (брифинг Часть 0, §6.3).
_PHASE_DIRS = {
    "global": "00_global",
    "chapter_opening": "01_chapter_opening",
    "introducing_concept": "02_introducing_concept",
    "deriving_formula": "03_deriving_formula",
    "climax": "04_climax",
    "biohazards": "05_biohazards",
    "pauses": "06_pauses",
    "chapter_closing": "07_chapter_closing",
    "tasks": "08_tasks",
    "book_level": "09_book_level",
}

# Разметка термина в тексте главы: **[термин]{определение}**
# (брифинг Часть 2, §4.3). Из неё строится глоссарий.
_TERM_MARKUP = re.compile(r"\*\*\[(.+?)\]\{(.+?)\}\*\*", re.DOTALL)


class ContextToolError(Exception):
    """Базовая ошибка функций Группы A."""


class ContentNotFoundError(ContextToolError):
    """Запрошенный файл/глава отсутствует в репозитории.

    Это не баг сервера, а сигнал «контент ещё не создан». server.py
    превращает её в понятное сообщение для Claude в чате.
    """


# ─── get_book_info ────────────────────────────────────────────────────


def get_book_info(root: Path) -> dict[str, Any]:
    """Вернуть общую информацию о книге из ``book_meta/book_info.yaml``.

    Args:
        root: корень репозитория linalg-book.

    Returns:
        Словарь с полями title, audience, style, total_chapters_written,
        chapters_summary (как в book_info.yaml).

    Raises:
        ContentNotFoundError: если ``book_meta/book_info.yaml`` отсутствует.
        ContextToolError: если YAML невалидный.

    Example:
        >>> info = get_book_info(Path("D:/projects/linalg-book"))
        >>> info["title"]
        'Линейная алгебра, по-человечески'
    """
    path = root / _BOOK_META / "book_info.yaml"
    try:
        raw = cache.read_text(path)
    except FileNotFoundError as e:
        raise ContentNotFoundError(
            f"book_info.yaml не найден по пути {path}. "
            f"Создайте его вручную (см. брифинг Часть 0, §6.1)."
        ) from e
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        raise ContextToolError(f"book_info.yaml невалидный YAML: {e}") from e
    if not isinstance(data, dict):
        raise ContextToolError(
            f"book_info.yaml должен содержать словарь на верхнем уровне, "
            f"получено {type(data).__name__}"
        )
    return data


# ─── get_style_guide ──────────────────────────────────────────────────


def get_style_guide(root: Path) -> str:
    """Вернуть полный текст стилгайда из ``book_meta/style_guide.md``.

    Args:
        root: корень репозитория.

    Returns:
        Markdown-строка с правилами стиля.

    Raises:
        ContentNotFoundError: если ``book_meta/style_guide.md`` отсутствует.
    """
    path = root / _BOOK_META / "style_guide.md"
    try:
        return cache.read_text(path)
    except FileNotFoundError as e:
        raise ContentNotFoundError(
            f"style_guide.md не найден по пути {path}. "
            f"Создайте его вручную (см. брифинг Часть 0, §6.2)."
        ) from e


# ─── get_chapter ──────────────────────────────────────────────────────


def _chapter_dir(root: Path, chapter_number: int) -> Path:
    """Папка главы: chapters/chapter_NN (NN с ведущим нулём, 2 цифры)."""
    return root / _CHAPTERS / f"chapter_{chapter_number:02d}"


def _resolve_chapter_file(chapter_dir: Path) -> tuple[Path, str]:
    """Выбрать файл главы: финальный chapter.md, иначе черновик draft.md.

    Returns:
        (path, source) где source ∈ {"chapter.md", "draft.md"}.

    Raises:
        ContentNotFoundError: если нет ни chapter.md, ни draft.md.
    """
    final = chapter_dir / "chapter.md"
    if final.is_file():
        return final, "chapter.md"
    draft = chapter_dir / "draft.md"
    if draft.is_file():
        return draft, "draft.md"
    raise ContentNotFoundError(
        f"В {chapter_dir} нет ни chapter.md, ни draft.md. Глава ещё не написана?"
    )


def _split_sections(content: str) -> list[tuple[str, str]]:
    """Разбить Markdown на разделы по заголовкам ``## ``.

    Returns:
        Список (heading_text, section_body), где heading_text — текст
        заголовка без ``## ``. Преамбула до первого ``## `` идёт под
        пустым heading "".
    """
    sections: list[tuple[str, str]] = []
    current_heading = ""
    current_lines: list[str] = []
    for line in content.splitlines():
        if line.startswith("## "):
            sections.append((current_heading, "\n".join(current_lines).strip()))
            current_heading = line[3:].strip()
            current_lines = []
        else:
            current_lines.append(line)
    sections.append((current_heading, "\n".join(current_lines).strip()))
    return sections


def _extract_section(content: str, section: str) -> str:
    """Вернуть текст конкретного раздела главы.

    Args:
        content: полный текст главы.
        section: "summary" (раздел «Что мы теперь знаем»),
            "bridge" (раздел «Мостик к следующей главе»), либо номер
            раздела как строка ("1", "4") — заголовок вида ``## N. ...``.

    Raises:
        ContentNotFoundError: если раздел не найден.
    """
    sections = _split_sections(content)

    def find(predicate) -> str | None:
        for heading, body in sections:
            if predicate(heading):
                # Возвращаем заголовок + тело, чтобы Claude видел контекст.
                return f"## {heading}\n\n{body}".strip()
        return None

    if section == "summary":
        result = find(lambda h: "что мы теперь знаем" in h.lower())
        label = "«Что мы теперь знаем»"
    elif section == "bridge":
        result = find(lambda h: "мостик" in h.lower())
        label = "«Мостик к следующей главе»"
    else:
        # Номер раздела: заголовок начинается с "N." или "N " (после
        # возможного ведущего маркера вроде ⚠).
        num = section.strip()
        result = find(
            lambda h: h.lstrip("⚠ ").startswith(f"{num}.")
            or h.lstrip("⚠ ").startswith(f"{num} ")
        )
        label = f"раздел {num}"

    if result is None:
        raise ContentNotFoundError(f"В главе не найден {label}.")
    return result


def get_chapter(
    root: Path,
    chapter_number: int,
    section: str = "all",
) -> dict[str, Any]:
    """Вернуть содержание написанной главы или её части.

    Args:
        root: корень репозитория.
        chapter_number: номер главы (1, 2, ...).
        section: "all" (вся глава, по умолчанию), "summary"
            (раздел «Что мы теперь знаем»), "bridge" (раздел «Мостик к
            следующей главе»), либо номер раздела как строка ("1", "4").

    Returns:
        Словарь:
            chapter_number — номер;
            source — "chapter.md" (финальная) или "draft.md" (черновик);
            section — что запрашивали;
            title — H1-заголовок главы (если есть, иначе None);
            content — текст главы или запрошенной части.

    Raises:
        ContentNotFoundError: если папки/файла главы нет, или раздел
            не найден.
    """
    chapter_dir = _chapter_dir(root, chapter_number)
    path, source = _resolve_chapter_file(chapter_dir)
    full_text = cache.read_text(path)

    # H1-заголовок главы — первая строка вида "# ...".
    title: str | None = None
    for line in full_text.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            break

    content = full_text if section == "all" else _extract_section(full_text, section)

    return {
        "chapter_number": chapter_number,
        "source": source,
        "section": section,
        "title": title,
        "content": content,
    }


# ─── вспомогательное: YAML-фронтматтер ────────────────────────────────


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Разобрать YAML-фронтматтер в начале Markdown-файла.

    Формат::

        ---
        id: open_self_deprecation
        russian_name: ...
        ---
        тело документа

    Делаем разбор сами (не через python-frontmatter), чтобы не тащить
    лишнюю зависимость: формат тривиален, а сервер должен быть лёгким
    (брифинг Часть 1, §6 «зависимости минимальны»).

    Args:
        text: полный текст файла.

    Returns:
        ``(metadata, body)``. Если фронтматтера нет — ``({}, text)``.

    Raises:
        ContextToolError: если фронтматтер открыт ``---``, но YAML внутри
            невалиден либо не является словарём.
    """
    stripped = text.lstrip("﻿")  # убрать возможный BOM
    lines = stripped.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, text
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            fm_text = "\n".join(lines[1:i])
            body = "\n".join(lines[i + 1 :]).lstrip("\n")
            try:
                meta = yaml.safe_load(fm_text) or {}
            except yaml.YAMLError as e:
                raise ContextToolError(f"невалидный YAML-фронтматтер: {e}") from e
            if not isinstance(meta, dict):
                raise ContextToolError(
                    f"фронтматтер должен быть словарём, получено {type(meta).__name__}"
                )
            return meta, body
    # Открывающий "---" есть, закрывающего нет — считаем, что это просто
    # горизонтальная черта, а не фронтматтер.
    return {}, text


def _extract_h1_section(
    body: str,
    *aliases: str,
    prefix: str | None = None,
) -> str | None:
    """Вернуть текст H1-раздела тела паттерна по заголовку.

    Тела паттернов размечены H1-заголовками (``# Суть``,
    ``# Когда применять`` …). Берём тело раздела (без строки заголовка)
    от совпавшего заголовка до следующего H1.

    Сопоставление регистронезависимое: либо точное совпадение с одним из
    ``aliases``, либо (если задан ``prefix``) — заголовок начинается с
    ``prefix`` (для разнородных «Пример из главы N»). Строки внутри
    ``` ```-ограждённых блоков кода не считаются заголовками.

    Returns:
        Текст раздела или ``None``, если ни один заголовок не подошёл
        (или раздел пуст).
    """
    targets = {a.strip().lower() for a in aliases}
    pref = prefix.strip().lower() if prefix else None

    def is_target(heading: str) -> bool:
        h = heading.strip().lower()
        return h in targets or (pref is not None and h.startswith(pref))

    collecting = False
    collected: list[str] = []
    in_fence = False
    for line in body.split("\n"):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            if collecting:
                collected.append(line)
            continue
        if not in_fence and line.startswith("# "):
            if collecting:
                break  # следующий H1 — конец нашего раздела
            if is_target(line[2:]):
                collecting = True
            continue
        if collecting:
            collected.append(line)
    if not collecting:
        return None
    return "\n".join(collected).strip() or None


# ─── вспомогательное: обход metadata.json глав ────────────────────────


def _iter_chapter_metadata(root: Path) -> Iterator[tuple[int, dict[str, Any]]]:
    """Пройти по всем ``chapters/chapter_NN/metadata.json``.

    Yields:
        Пары ``(chapter_number, metadata_dict)`` в порядке возрастания
        номера. Битый JSON или нечисловое имя папки — пропускаются с
        предупреждением в лог (один сломанный файл не должен ронять обход).
    """
    chapters_dir = root / _CHAPTERS
    if not chapters_dir.is_dir():
        return
    by_num: dict[int, Path] = {}
    for md_path in chapters_dir.glob("chapter_*/metadata.json"):
        name = md_path.parent.name.removeprefix("chapter_")
        try:
            by_num[int(name)] = md_path
        except ValueError:
            log.warning("пропускаю папку с нечисловым номером: %s", md_path.parent)
    for num in sorted(by_num):
        md_path = by_num[num]
        try:
            data = json.loads(cache.read_text(md_path))
        except FileNotFoundError:
            continue
        except json.JSONDecodeError as e:
            log.warning("пропускаю невалидный metadata.json %s: %s", md_path, e)
            continue
        if isinstance(data, dict):
            yield num, data


# ─── get_chapter_plan ─────────────────────────────────────────────────


def get_chapter_plan(root: Path, chapter_number: int) -> dict[str, Any]:
    """Вернуть план главы целиком — содержимое ``metadata.json``.

    Args:
        root: корень репозитория.
        chapter_number: номер главы.

    Returns:
        Распарсенный объект ``chapters/chapter_NN/metadata.json``.

    Raises:
        ContentNotFoundError: если ``metadata.json`` главы отсутствует
            (план ещё не составлен).
        ContextToolError: если JSON невалиден или это не объект.

    Example:
        >>> plan = get_chapter_plan(Path("D:/projects/linalg-book"), 4)
        >>> plan["chapter_number"]
        4
    """
    path = _chapter_dir(root, chapter_number) / "metadata.json"
    try:
        raw = cache.read_text(path)
    except FileNotFoundError as e:
        raise ContentNotFoundError(
            f"metadata.json для главы {chapter_number} не найден ({path}). "
            f"План главы ещё не составлен?"
        ) from e
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ContextToolError(
            f"metadata.json главы {chapter_number} — невалидный JSON: {e}"
        ) from e
    if not isinstance(data, dict):
        raise ContextToolError(
            f"metadata.json главы {chapter_number} должен быть объектом, "
            f"получено {type(data).__name__}"
        )
    return data


# ─── get_pending_promises ─────────────────────────────────────────────


def get_pending_promises(root: Path, for_chapter: int) -> list[dict[str, Any]]:
    """Вернуть обещания, которые должны быть отработаны в главе ``for_chapter``.

    Каждый мостик (``bridge_to_next.promises`` в ``metadata.json``) даёт
    обещания для **следующей** главы. Поэтому обещания, висящие на главе
    N, — это ``promises`` из главы N−1.

    Сервер не отслеживает факт выполнения обещаний (это делает
    ``check_promises`` уже на этапе проверки готового черновика). Здесь —
    только «что было обещано к этой главе».

    Args:
        root: корень репозитория.
        for_chapter: номер главы, для которой собираем обещания.

    Returns:
        Список словарей ``{promise, made_in_chapter, due_in_chapter,
        section_of_origin}``. Пустой, если предыдущая глава ничего не
        обещала (или её ещё нет).

    Example:
        >>> get_pending_promises(Path("D:/projects/linalg-book"), 5)
        [{'promise': 'обратная матрица ...', 'made_in_chapter': 4,
          'due_in_chapter': 5, 'section_of_origin': 'bridge_to_next'}, ...]
    """
    result: list[dict[str, Any]] = []
    for num, data in _iter_chapter_metadata(root):
        due_in = num + 1
        if due_in != for_chapter:
            continue
        bridge = data.get("bridge_to_next")
        promises = bridge.get("promises") if isinstance(bridge, dict) else None
        if not isinstance(promises, list):
            continue
        for promise in promises:
            if not isinstance(promise, str):
                continue
            result.append(
                {
                    "promise": promise,
                    "made_in_chapter": num,
                    "due_in_chapter": due_in,
                    "section_of_origin": "bridge_to_next",
                }
            )
    return result


# ─── get_glossary ─────────────────────────────────────────────────────


def get_glossary(root: Path) -> list[dict[str, Any]]:
    """Собрать глоссарий из разметки терминов в главах.

    Источник истины — разметка ``**[термин]{определение}**`` прямо в
    тексте глав (брифинг Часть 2, §4.3), а не производный
    ``book_meta/glossary.md`` (его генерирует ``metadata_builder.py`` для
    вёрстки книги). Так глоссарий всегда синхронен с актуальным текстом,
    а функция остаётся детерминированной и структурированной.

    Для каждой главы берётся ``chapter.md`` (либо ``draft.md``, если
    финальной версии ещё нет). Термин фиксируется по **первому** появлению.

    Args:
        root: корень репозитория.

    Returns:
        Список ``{term, definition, introduced_in}`` в порядке первого
        появления (по возрастанию номера главы). Пустой, если разметки
        терминов ещё нет.
    """
    chapters_dir = root / _CHAPTERS
    if not chapters_dir.is_dir():
        return []
    nums: list[int] = []
    for d in chapters_dir.glob("chapter_*"):
        if d.is_dir():
            try:
                nums.append(int(d.name.removeprefix("chapter_")))
            except ValueError:
                continue
    seen: dict[str, dict[str, Any]] = {}
    for num in sorted(nums):
        try:
            path, _ = _resolve_chapter_file(_chapter_dir(root, num))
        except ContentNotFoundError:
            continue
        text = cache.read_text(path)
        for match in _TERM_MARKUP.finditer(text):
            term = match.group(1).strip()
            definition = match.group(2).strip()
            if term not in seen:
                seen[term] = {
                    "term": term,
                    "definition": definition,
                    "introduced_in": num,
                }
    return list(seen.values())


# ─── get_patterns_for_phase ───────────────────────────────────────────


def get_patterns_for_phase(root: Path, phase: str) -> list[dict[str, Any]]:
    """Вернуть паттерны изложения для конкретной фазы главы.

    Читает ``patterns/<phase>/*.md``, разбирает YAML-фронтматтер и тело
    каждого файла. Возвращает карточку-сводку; полную инструкцию («тело»)
    не отдаёт — для неё есть :func:`get_pattern_details`.

    Поля собираются устойчиво к двум форматам паттернов, встречающимся в
    репозитории: ключ берётся из фронтматтера, а если его там нет —
    из соответствующего H1-раздела тела:

    - ``task_type``        ← ``task_type`` | ``category``;
    - ``frequency``        ← ``frequency`` | ``frequency_per_chapter`` |
      ``frequency_per_book``;
    - ``summary``          ← ``summary`` | раздел ``# Суть`` / ``# Описание``;
    - ``when_to_apply``    ← ``when_to_apply`` | раздел ``# Когда применять``;
    - ``when_not_to_apply``← ``when_not_to_apply`` |
      раздел ``# Когда не применять`` / ``# Не применять``;
    - ``example``          ← ``example`` | первый раздел ``# Пример …``.

    Args:
        root: корень репозитория.
        phase: одна из фаз: ``global``, ``chapter_opening``,
            ``introducing_concept``, ``deriving_formula``, ``climax``,
            ``biohazards``, ``pauses``, ``chapter_closing``, ``tasks``,
            ``book_level``.

    Returns:
        Список словарей с полями ``id``, ``russian_name``, ``task_type``,
        ``frequency``, ``summary``, ``when_to_apply``, ``when_not_to_apply``,
        ``example``. Отсутствующие поля — ``None``. Если папки фазы ещё
        нет — пустой список.

    Raises:
        ContextToolError: если ``phase`` — неизвестное имя фазы.
    """
    if phase not in _PHASE_DIRS:
        valid = ", ".join(_PHASE_DIRS)
        raise ContextToolError(f"Неизвестная фаза «{phase}». Допустимые: {valid}.")
    phase_dir = root / _PATTERNS / _PHASE_DIRS[phase]
    if not phase_dir.is_dir():
        log.info("get_patterns_for_phase: каталог %s отсутствует", phase_dir)
        return []
    result: list[dict[str, Any]] = []
    for md_path in sorted(phase_dir.glob("*.md")):
        meta, body = _parse_frontmatter(cache.read_text(md_path))
        result.append(
            {
                "id": meta.get("id") or md_path.stem,
                "russian_name": meta.get("russian_name"),
                "task_type": meta.get("task_type") or meta.get("category"),
                "frequency": (
                    meta.get("frequency")
                    or meta.get("frequency_per_chapter")
                    or meta.get("frequency_per_book")
                ),
                "summary": meta.get("summary")
                or _extract_h1_section(body, "Суть", "Описание"),
                "when_to_apply": meta.get("when_to_apply")
                or _extract_h1_section(body, "Когда применять"),
                "when_not_to_apply": meta.get("when_not_to_apply")
                or _extract_h1_section(body, "Когда не применять", "Не применять"),
                "example": meta.get("example")
                or _extract_h1_section(body, prefix="Пример"),
            }
        )
    return result


# ─── get_pattern_details ──────────────────────────────────────────────


def get_pattern_details(root: Path, pattern_id: str) -> str:
    """Вернуть полный Markdown-текст файла паттерна по его ID.

    Ищет файл по всему дереву ``patterns/``: сперва по имени файла
    (``<pattern_id>.md``), затем по полю ``id`` во фронтматтере. Возвращает
    содержимое файла целиком, включая раздел «Инструкция для LLM».

    Args:
        root: корень репозитория.
        pattern_id: идентификатор паттерна (например, ``biohazard_marker``).

    Returns:
        Полный текст файла паттерна.

    Raises:
        ContentNotFoundError: если каталога ``patterns/`` нет или паттерн
            с таким ID не найден.
    """
    patterns_root = root / _PATTERNS
    if not patterns_root.is_dir():
        raise ContentNotFoundError(
            f"Каталог patterns/ отсутствует ({patterns_root}). "
            f"Паттерны ещё не добавлены."
        )
    candidates = sorted(patterns_root.glob("**/*.md"))
    # 1) по имени файла — самый частый и дешёвый случай.
    for md_path in candidates:
        if md_path.stem == pattern_id:
            return cache.read_text(md_path)
    # 2) по полю id во фронтматтере.
    for md_path in candidates:
        text = cache.read_text(md_path)
        meta, _ = _parse_frontmatter(text)
        if meta.get("id") == pattern_id:
            return text
    raise ContentNotFoundError(
        f"Паттерн «{pattern_id}» не найден в patterns/. "
        f"Проверьте id (поле frontmatter ``id:`` или имя файла без .md)."
    )


# ─── get_conflicts_table ──────────────────────────────────────────────


def get_conflicts_table(root: Path) -> str:
    """Вернуть таблицу конфликтов паттернов из ``patterns/00_conflicts.md``.

    Args:
        root: корень репозитория.

    Returns:
        Markdown-текст файла (таблица несовместимых паттернов).

    Raises:
        ContentNotFoundError: если файла нет.
    """
    path = root / _PATTERNS / "00_conflicts.md"
    try:
        return cache.read_text(path)
    except FileNotFoundError as e:
        raise ContentNotFoundError(f"Таблица конфликтов не найдена ({path}).") from e
