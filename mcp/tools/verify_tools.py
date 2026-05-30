"""Группа B — проверки готовой главы (Часть 0 брифинга, §7).

Детерминированные проверки черновика/финальной главы. Как и Группа A,
**только читают файлы репозитория** — никакого LLM, SymPy, сети.

Группа B:
- :func:`check_structure` — структура прозы сверяется с планом
  (``metadata.json``): есть ли H1, все ли заявленные разделы на месте,
  совпадают ли заголовки, есть ли итог и мостик.
- :func:`check_markers`   — маркеры биохазарда ``⚠``: их число против
  плана, частота против паттерна ``biohazard_marker``, и стоят ли они
  в начале блока.
- :func:`check_terms`     — термины из плана (``new_terms_introduced``)
  сверяются с разметкой ``**[термин]{определение}**`` в прозе и с
  глоссарием предыдущих глав (повторный ввод термина).
- :func:`verify_chapter`  — оркестратор: запускает все проверки и сводит
  находки в один отчёт с вердиктом ``ok`` / ``warn`` / ``fail``.

Каждая проверка (``check_*``) возвращает **список находок**. Находка —
словарь::

    {
        "check":    "check_structure",      # какая проверка нашла
        "severity": "error" | "warning" | "info",
        "code":     "missing_section",      # машинный код (для тестов
                                            # и будущего checks_config.yaml)
        "message":  "человекочитаемое описание",
        "location": "где именно" | None,
    }

Коды и их строгость (захардкожены; ``checks_config.yaml`` появится, когда
проверок станет достаточно, чтобы было что настраивать):

check_structure
    missing_h1              error    — нет H1-заголовка главы
    missing_metadata        error    — нет metadata.json, нечем сверять план
    missing_section         error    — раздел из плана отсутствует в прозе
    section_title_mismatch  warning  — заголовок раздела в прозе ≠ плану
    sections_out_of_order   warning  — номера разделов не по возрастанию
    duplicate_section       warning  — номер раздела встречается дважды
    missing_summary         warning  — нет раздела-итога «Что мы теперь знаем»
    missing_bridge          warning  — план обещает мостик, а его нет в прозе

check_markers
    biohazard_count_mismatch warning — число ⚠ ≠ числу биохазардов в плане
    marker_frequency_exceeded warning — ⚠ больше, чем допускает паттерн
    marker_placement         info    — ⚠ не в начале блока/заголовка

check_terms
    term_not_marked         warning  — термин из плана не размечен в прозе
    unplanned_term_marked   info     — в прозе размечен термин не из плана
    term_reintroduced       warning  — термин уже вводился в более ранней главе

Вердикт ``verify_chapter``: ``fail`` если есть хоть один ``error``;
иначе ``warn`` если есть ``warning``; иначе ``ok``.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import cache
from tools.context_tools import (
    _TERM_MARKUP,
    ContentNotFoundError,
    _chapter_dir,
    _parse_frontmatter,
    _resolve_chapter_file,
    get_chapter_plan,
    get_glossary,
    get_pattern_details,
)

log = logging.getLogger("linalg-book-mcp.verify_tools")

# Маркер биохазарда (см. patterns/05_biohazards/biohazard_marker.md).
_MARKER = "⚠"

# Заголовок второго уровня: "## ..." (текст после "## ").
_H2_RE = re.compile(r"^##\s+(.*)$")

# Ведущий номер раздела в заголовке: "4. ..." или "⚠ 4. ..." → (4, остаток).
# Возможный ведущий маркер ⚠ перед номером допускаем и отбрасываем.
_NUM_RE = re.compile(r"^(?:⚠\s*)?(\d+)\.\s*(.*)$")


# ─── вспомогательное ──────────────────────────────────────────────────


def _finding(
    check: str,
    severity: str,
    code: str,
    message: str,
    location: str | None = None,
) -> dict[str, Any]:
    """Собрать словарь-находку единого формата."""
    return {
        "check": check,
        "severity": severity,
        "code": code,
        "message": message,
        "location": location,
    }


def _read_chapter(root: Path, chapter_number: int) -> tuple[str, str]:
    """Прочитать текст главы.

    Returns:
        ``(content, source)``; source ∈ {"chapter.md", "draft.md"}.

    Raises:
        ContentNotFoundError: если главы (chapter.md/draft.md) нет —
            проверять нечего, глава не написана.
    """
    path, source = _resolve_chapter_file(_chapter_dir(root, chapter_number))
    return cache.read_text(path), source


def _load_meta(root: Path, chapter_number: int) -> dict[str, Any] | None:
    """Прочитать metadata.json главы, либо None, если его нет."""
    try:
        return get_chapter_plan(root, chapter_number)
    except ContentNotFoundError:
        return None


def _h2_headings(content: str) -> list[str]:
    """Вернуть тексты всех заголовков ``## `` (без префикса) по порядку."""
    headings: list[str] = []
    for line in content.splitlines():
        m = _H2_RE.match(line)
        if m:
            headings.append(m.group(1).strip())
    return headings


def _split_num_title(heading: str) -> tuple[int | None, str]:
    """Разобрать заголовок на (номер, заголовок-без-номера).

    Если заголовок не начинается с номера — ``(None, исходный_текст)``.
    """
    m = _NUM_RE.match(heading)
    if not m:
        return None, heading
    return int(m.group(1)), m.group(2).strip()


def _normalize_title(text: str) -> str:
    """Нормализовать заголовок для сравнения: схлопнуть пробелы, lower."""
    return re.sub(r"\s+", " ", text).strip().lower()


def _has_h1(content: str) -> bool:
    """Есть ли в главе H1-заголовок (строка ``# ...``, но не ``## ...``)."""
    for line in content.splitlines():
        if line.startswith("# "):
            return True
    return False


def _biohazard_max_per_chapter(root: Path) -> int | None:
    """Максимум биохазардов на главу из паттерна ``biohazard_marker``.

    Берёт ``frequency_per_chapter`` из фронтматтера паттерна и вытаскивает
    наибольшее число (например, "2-3 раза, не больше" → 3). None, если
    паттерн не найден или в строке нет чисел.
    """
    try:
        text = get_pattern_details(root, "biohazard_marker")
    except ContentNotFoundError:
        return None
    meta, _ = _parse_frontmatter(text)
    freq = meta.get("frequency_per_chapter") or meta.get("frequency")
    if not isinstance(freq, str):
        return None
    nums = [int(n) for n in re.findall(r"\d+", freq)]
    return max(nums) if nums else None


# ─── check_structure ──────────────────────────────────────────────────


def check_structure(root: Path, chapter_number: int) -> list[dict[str, Any]]:
    """Сверить структуру прозы главы с её планом (``metadata.json``).

    Проверяет: наличие H1; наличие каждого раздела из ``sections``;
    совпадение заголовков; порядок и уникальность номеров; наличие
    раздела-итога и мостика (если план обещает ``bridge_to_next``).

    Args:
        root: корень репозитория.
        chapter_number: номер главы.

    Returns:
        Список находок (см. модульный docstring). Пустой — структура чистая.

    Raises:
        ContentNotFoundError: если файла главы нет (глава не написана).
    """
    content, _ = _read_chapter(root, chapter_number)
    findings: list[dict[str, Any]] = []
    check = "check_structure"

    # 1) H1.
    if not _has_h1(content):
        findings.append(
            _finding(
                check,
                "error",
                "missing_h1",
                "В главе нет H1-заголовка (строки вида «# Глава N. …»).",
            )
        )

    headings = _h2_headings(content)
    # Карта: номер раздела → заголовок-без-номера (первое появление).
    prose_sections: dict[int, str] = {}
    prose_order: list[int] = []
    for h in headings:
        num, title = _split_num_title(h)
        if num is None:
            continue
        prose_order.append(num)
        if num not in prose_sections:
            prose_sections[num] = title

    # 2) Порядок и дубликаты номеров.
    numbered = prose_order
    seen: set[int] = set()
    for i, num in enumerate(numbered):
        if num in seen:
            findings.append(
                _finding(
                    check,
                    "warning",
                    "duplicate_section",
                    f"Номер раздела {num} встречается в прозе более одного раза.",
                    location=f"## {num}.",
                )
            )
        seen.add(num)
    if numbered != sorted(numbered):
        findings.append(
            _finding(
                check,
                "warning",
                "sections_out_of_order",
                f"Номера разделов в прозе идут не по возрастанию: {numbered}.",
            )
        )

    # 3) Сверка с планом.
    meta = _load_meta(root, chapter_number)
    if meta is None:
        findings.append(
            _finding(
                check,
                "error",
                "missing_metadata",
                "Нет metadata.json — план главы не с чем сверять.",
            )
        )
    else:
        sections = meta.get("sections")
        if isinstance(sections, list):
            for sec in sections:
                if not isinstance(sec, dict):
                    continue
                num = sec.get("number")
                title = sec.get("title", "")
                if not isinstance(num, int):
                    continue
                if num not in prose_sections:
                    findings.append(
                        _finding(
                            check,
                            "error",
                            "missing_section",
                            f"Раздел {num} «{title}» есть в плане, "
                            f"но отсутствует в прозе.",
                            location=f"metadata: sections[number={num}]",
                        )
                    )
                    continue
                # Сравниваем заголовки. В плане заголовок может уже
                # включать номер ("4. ⚠ …") или нет — нормализуем обе
                # стороны, отбросив ведущий номер у планового заголовка.
                _, plan_title = _split_num_title(str(title))
                if _normalize_title(plan_title) != _normalize_title(
                    prose_sections[num]
                ):
                    findings.append(
                        _finding(
                            check,
                            "warning",
                            "section_title_mismatch",
                            f"Заголовок раздела {num}: в плане «{title}», "
                            f"в прозе «{prose_sections[num]}».",
                            location=f"## {num}.",
                        )
                    )

        # 4) Раздел-итог.
        if not any(
            "что мы" in h.lower()
            and ("знаем" in h.lower() or "узнали" in h.lower() or "поняли" in h.lower())
            for h in headings
        ):
            findings.append(
                _finding(
                    check,
                    "warning",
                    "missing_summary",
                    "Нет раздела-итога («Что мы теперь знаем»).",
                )
            )

        # 5) Мостик (если план его обещает).
        if isinstance(meta.get("bridge_to_next"), dict):
            if not any("мостик" in h.lower() for h in headings):
                findings.append(
                    _finding(
                        check,
                        "warning",
                        "missing_bridge",
                        "План обещает bridge_to_next, но в прозе нет раздела "
                        "«Мостик к следующей главе».",
                    )
                )

    return findings


# ─── check_markers ────────────────────────────────────────────────────


def _marker_lines(content: str) -> list[tuple[int, str]]:
    """Строки (1-индекс) с маркером ⚠ и сам текст строки."""
    return [
        (i, line)
        for i, line in enumerate(content.splitlines(), start=1)
        if _MARKER in line
    ]


def _placement_ok(line: str) -> bool:
    """⚠ стоит «в начале блока»?

    Допустимо: маркер в заголовке (строка начинается с ``#``), либо
    строка после отбрасывания ведущих markdown-токенов (> - * пробелы,
    жирность ``**``) начинается с ⚠.
    """
    stripped = line.lstrip()
    if stripped.startswith("#"):  # любой заголовок — канонная форма врезки
        return True
    # отбрасываем ведущие токены списка/цитаты/жирности
    core = re.sub(r"^[>\-\*\s]+", "", stripped)
    core = re.sub(r"^\*\*\s*", "", core)
    return core.startswith(_MARKER)


def check_markers(root: Path, chapter_number: int) -> list[dict[str, Any]]:
    """Проверить маркеры биохазарда ``⚠`` в главе.

    Проверяет: число маркеров против плана (``biohazards_in_chapter``);
    частоту против паттерна ``biohazard_marker``; стоят ли маркеры в
    начале блока/заголовка.

    Args:
        root: корень репозитория.
        chapter_number: номер главы.

    Returns:
        Список находок. Пустой — с маркерами всё в порядке.

    Raises:
        ContentNotFoundError: если файла главы нет.
    """
    content, _ = _read_chapter(root, chapter_number)
    findings: list[dict[str, Any]] = []
    check = "check_markers"

    marker_lines = _marker_lines(content)
    marker_count = content.count(_MARKER)

    # 1) Число маркеров против плана.
    meta = _load_meta(root, chapter_number)
    if meta is not None:
        declared = meta.get("biohazards_in_chapter")
        if isinstance(declared, list):
            n_declared = len(declared)
            if n_declared != marker_count:
                findings.append(
                    _finding(
                        check,
                        "warning",
                        "biohazard_count_mismatch",
                        f"В плане заявлено биохазардов: {n_declared}, "
                        f"а маркеров ⚠ в прозе: {marker_count}.",
                    )
                )

    # 2) Частота против паттерна.
    cap = _biohazard_max_per_chapter(root)
    if cap is not None and marker_count > cap:
        findings.append(
            _finding(
                check,
                "warning",
                "marker_frequency_exceeded",
                f"Маркеров ⚠ в главе: {marker_count}, а паттерн "
                f"biohazard_marker рекомендует не больше {cap}.",
            )
        )

    # 3) Размещение каждого маркера.
    for lineno, line in marker_lines:
        if not _placement_ok(line):
            findings.append(
                _finding(
                    check,
                    "info",
                    "marker_placement",
                    "Маркер ⚠ должен стоять в начале блока или заголовка.",
                    location=f"строка {lineno}",
                )
            )

    return findings


# ─── check_terms ──────────────────────────────────────────────────────


def _marked_terms(content: str) -> list[str]:
    """Термины, размеченные в прозе как ``**[термин]{определение}**``.

    Возвращает имена терминов по порядку появления (с возможными
    повторами); определение игнорируем — здесь важен сам факт разметки.
    """
    return [
        m.group(1).strip() for m in _TERM_MARKUP.finditer(content) if m.group(1).strip()
    ]


def _planned_terms(meta: dict[str, Any]) -> list[str]:
    """Имена терминов из ``new_terms_introduced`` плана (устойчиво к мусору)."""
    terms: list[str] = []
    declared = meta.get("new_terms_introduced")
    if isinstance(declared, list):
        for item in declared:
            if isinstance(item, dict):
                term = item.get("term")
                if isinstance(term, str) and term.strip():
                    terms.append(term.strip())
    return terms


def check_terms(root: Path, chapter_number: int) -> list[dict[str, Any]]:
    """Сверить термины главы: план ↔ разметка в прозе ↔ глоссарий.

    Три находки:

    - ``term_not_marked`` (warning) — термин заявлен в плане
      (``new_terms_introduced``), но не размечен в прозе как
      ``**[термин]{определение}**``.
    - ``unplanned_term_marked`` (info) — термин размечен в прозе, но его
      нет в плане.
    - ``term_reintroduced`` (warning) — термин размечен в этой главе как
      новый, хотя уже вводился в **более ранней** главе (по глоссарию).

    Сравнение имён регистронезависимое, пробелы схлопываются. Если
    ``metadata.json`` нет — возвращает ``[]`` (ошибку ``missing_metadata``
    выдаёт :func:`check_structure`, дублировать не нужно).

    Args:
        root: корень репозитория.
        chapter_number: номер главы.

    Returns:
        Список находок. Пустой — с терминами всё в порядке.

    Raises:
        ContentNotFoundError: если файла главы нет (глава не написана).
    """
    content, _ = _read_chapter(root, chapter_number)
    check = "check_terms"

    meta = _load_meta(root, chapter_number)
    if meta is None:
        return []

    findings: list[dict[str, Any]] = []
    planned = _planned_terms(meta)
    marked = _marked_terms(content)
    planned_norm = {_normalize_title(t) for t in planned}
    marked_norm = {_normalize_title(t) for t in marked}

    # 1) Заявлен в плане, но не размечен в прозе.
    for term in planned:
        if _normalize_title(term) not in marked_norm:
            findings.append(
                _finding(
                    check,
                    "warning",
                    "term_not_marked",
                    f"Термин «{term}» заявлен в плане (new_terms_introduced), "
                    f"но не размечен в прозе как **[термин]{{определение}}**.",
                    location=f"metadata: new_terms_introduced[{term}]",
                )
            )

    # 2) Размечен в прозе, но его нет в плане (по первому появлению).
    emitted_unplanned: set[str] = set()
    for term in marked:
        n = _normalize_title(term)
        if n not in planned_norm and n not in emitted_unplanned:
            emitted_unplanned.add(n)
            findings.append(
                _finding(
                    check,
                    "info",
                    "unplanned_term_marked",
                    f"Термин «{term}» размечен в прозе, но его нет в плане "
                    f"(new_terms_introduced).",
                )
            )

    # 3) Повторный ввод: термин уже вводился в более ранней главе.
    introduced_in: dict[str, int] = {
        _normalize_title(g["term"]): g["introduced_in"] for g in get_glossary(root)
    }
    emitted_reintro: set[str] = set()
    for term in marked:
        n = _normalize_title(term)
        first = introduced_in.get(n)
        if first is not None and first < chapter_number and n not in emitted_reintro:
            emitted_reintro.add(n)
            findings.append(
                _finding(
                    check,
                    "warning",
                    "term_reintroduced",
                    f"Термин «{term}» размечен в главе {chapter_number} как новый, "
                    f"но уже вводился в главе {first}.",
                )
            )

    return findings


# ─── verify_chapter ───────────────────────────────────────────────────

# Все проверки, которые запускает оркестратор. Расширяется со срезами.
_ALL_CHECKS = (check_structure, check_markers, check_terms)


def verify_chapter(root: Path, chapter_number: int) -> dict[str, Any]:
    """Запустить все проверки главы и свести находки в один отчёт.

    Args:
        root: корень репозитория.
        chapter_number: номер главы.

    Returns:
        Словарь::

            {
              "chapter_number": N,
              "source": "chapter.md" | "draft.md",
              "checks_run": ["check_structure", "check_markers"],
              "counts": {"error": E, "warning": W, "info": I},
              "verdict": "ok" | "warn" | "fail",
              "findings": [ ...все находки... ],
            }

    Raises:
        ContentNotFoundError: если файла главы нет (глава не написана).
    """
    _, source = _read_chapter(root, chapter_number)

    findings: list[dict[str, Any]] = []
    for fn in _ALL_CHECKS:
        findings.extend(fn(root, chapter_number))

    counts = {
        "error": sum(1 for f in findings if f["severity"] == "error"),
        "warning": sum(1 for f in findings if f["severity"] == "warning"),
        "info": sum(1 for f in findings if f["severity"] == "info"),
    }
    if counts["error"]:
        verdict = "fail"
    elif counts["warning"]:
        verdict = "warn"
    else:
        verdict = "ok"

    return {
        "chapter_number": chapter_number,
        "source": source,
        "checks_run": [fn.__name__ for fn in _ALL_CHECKS],
        "counts": counts,
        "verdict": verdict,
        "findings": findings,
    }
