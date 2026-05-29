"""Группа A — предоставление контекста (Часть 0 брифинга, §6).

Функции, отдающие Claude в чате контекст книги *до и во время* написания
главы. Все они **детерминированы**, читают только файлы репозитория,
ничего не генерируют.

Реализованы три базовые (брифинг §17 «минимальный рабочий MCP»):
- :func:`get_book_info`   — общая информация о книге.
- :func:`get_style_guide` — полный текст стилгайда.
- :func:`get_chapter`     — содержание написанной главы (или её части).

Остальные функции Группы A (паттерны, глоссарий, обещания, …) добавятся
следующими сеансами.

Каждая функция принимает ``root: Path`` — корень репозитория. Это делает
их тестируемыми без MCP и без переменных окружения: тест передаёт
``tmp_path``-фикстуру.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

import cache

# Имена подпапок дублируем сюда из config, чтобы context_tools не зависел
# от config (config — про определение корня, это забота server.py).
_BOOK_META = "book_meta"
_CHAPTERS = "chapters"


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
        f"В {chapter_dir} нет ни chapter.md, ни draft.md. "
        f"Глава ещё не написана?"
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
