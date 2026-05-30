r"""Группа B — проверки готовой главы (Часть 0 брифинга, §7).

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
- :func:`check_patterns`  — паттерны из плана (``sections[].patterns_used``)
  сверяются с библиотекой ``patterns/`` (неизвестные ID) и таблицей
  ``00_conflicts.md`` (конфликтующие/переигрывающие пары).
- :func:`check_promises`  — обещания мостика предыдущей главы
  (``bridge_to_next.promises``) сверяются с тем, что эта глава подхватила
  в ``previous_promises_to_fulfill`` (бухгалтерия смежности, без семантики).
- :func:`check_styleguide` — проза сверяется с механически проверяемой
  частью стилгайда: запрещённые канцелярские конструкции и нотация формул
  (``\times`` между числами). Семантика (залог, тон) — вне охвата.
- :func:`check_links`     — ссылки прозы сверяются с файловой системой:
  существуют ли локальные картинки ``![alt](images/...)`` и есть ли папка
  ``chapter_NN`` для каждой упомянутой «главы N».
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

Коды и их строгость по умолчанию (см. ниже). Дефолты можно точечно
переопределить через ``book_meta/checks_config.yaml`` — разреженные
оверрайды ``check → код → severity`` (``error`` / ``warning`` / ``info``,
либо ``off`` — убрать находку из отчёта совсем). Файла нет / битый /
неизвестный код → молча работают дефолты (см. :func:`_load_checks_config`,
:func:`_configurable`):

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

check_patterns
    pattern_unknown         warning  — ID паттерна не найден в patterns/
    pattern_conflict        warning  — пара из таблицы CONFLICT сосуществует
    pattern_redundancy      info     — пара из таблицы REDUNDANCY сосуществует

check_promises
    promises_not_carried    warning  — мостик прошлой главы что-то обещал,
                                       а эта глава ничего не подхватила
    promise_count_shortfall info     — подхвачено меньше пунктов, чем обещано

check_styleguide
    styleguide_forbidden_phrase warning — канцелярит из стоп-списка стилгайда
    styleguide_filler_word      info    — связка-наполнитель «является»
    styleguide_formula_notation warning — \times между числами (нужен \cdot)

check_links
    missing_image           error    — локальная картинка не найдена на диске
    broken_chapter_ref      warning  — нет папки chapter_NN для «главы N»

Вердикт ``verify_chapter``: ``fail`` если есть хоть один ``error``;
иначе ``warn`` если есть ``warning``; иначе ``ok``.
"""

from __future__ import annotations

import functools
import logging
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

import cache
from tools.context_tools import (
    _BOOK_META,
    _PATTERNS,
    _TERM_MARKUP,
    ContentNotFoundError,
    _chapter_dir,
    _parse_frontmatter,
    _resolve_chapter_file,
    get_chapter_plan,
    get_conflicts_table,
    get_glossary,
    get_pattern_details,
    get_pending_promises,
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


# ─── строгость кодов: book_meta/checks_config.yaml ────────────────────

_CHECKS_CONFIG_FILE = "checks_config.yaml"

# Допустимые значения строгости в конфиге. "off" — полностью убрать находку
# из отчёта (не считается ни в error/warning/info, ни в вердикт).
_VALID_SEVERITIES = frozenset({"error", "warning", "info", "off"})

# Сигнатура любой проверки Группы B.
_CheckFn = Callable[[Path, int], list[dict[str, Any]]]


def _load_checks_config(root: Path) -> dict[tuple[str, str], str]:
    """Прочитать ``book_meta/checks_config.yaml`` → карту оверрайдов строгости.

    Конфиг **разреженный**: перечисляет только коды, чью строгость нужно
    переопределить. Всё неупомянутое сохраняет дефолт, захардкоженный в коде.

    Формат::

        check_terms:
          unplanned_term_marked: "off"        # убрать находку совсем
        check_styleguide:
          styleguide_formula_notation: error  # поднять строгость

    Returns:
        ``{(check, code): severity}``, severity ∈ {error, warning, info, off}.
        Пустой словарь, если файла нет, он пуст или битый — тогда работают
        дефолты, и ни одна проверка не падает из-за конфига.

    Note:
        Голый ``off`` YAML 1.1 разбирает как булево ``False`` (как ``no`` и
        ``false``); такой ``False`` трактуем как «off». ``true``-подобные
        значения для строгости бессмысленны и отвергаются с предупреждением.
    """
    path = root / _BOOK_META / _CHECKS_CONFIG_FILE
    try:
        raw = cache.read_text(path)
    except FileNotFoundError:
        return {}
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        log.warning("%s: невалидный YAML, игнорирую (%s)", _CHECKS_CONFIG_FILE, e)
        return {}
    if not isinstance(data, dict):
        return {}

    overrides: dict[tuple[str, str], str] = {}
    for check, codes in data.items():
        if not isinstance(codes, dict):
            log.warning(
                "%s: секция %r должна быть словарём код→строгость, пропускаю",
                _CHECKS_CONFIG_FILE,
                check,
            )
            continue
        for code, sev in codes.items():
            if sev is False:  # голый off/no/false из YAML 1.1
                sev_norm = "off"
            elif isinstance(sev, str):
                sev_norm = sev.strip().lower()
            else:
                log.warning(
                    "%s: строгость %r для %s/%s не строка, пропускаю",
                    _CHECKS_CONFIG_FILE,
                    sev,
                    check,
                    code,
                )
                continue
            if sev_norm not in _VALID_SEVERITIES:
                log.warning(
                    "%s: неизвестная строгость %r для %s/%s "
                    "(ожидалось error/warning/info/off), пропускаю",
                    _CHECKS_CONFIG_FILE,
                    sev,
                    check,
                    code,
                )
                continue
            overrides[(str(check), str(code))] = sev_norm
    return overrides


def _apply_config(root: Path, findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Применить оверрайды строгости к находкам проверки.

    Переопределяет ``severity`` по карте :func:`_load_checks_config`; находки
    со строгостью ``off`` выбрасываются из списка. Если оверрайдов нет —
    возвращает находки без изменений.
    """
    overrides = _load_checks_config(root)
    if not overrides:
        return findings
    out: list[dict[str, Any]] = []
    for f in findings:
        sev = overrides.get((f["check"], f["code"]))
        if sev is None:
            out.append(f)
        elif sev == "off":
            continue
        else:
            out.append({**f, "severity": sev})
    return out


def _configurable(check_fn: _CheckFn) -> _CheckFn:
    """Декоратор: прогнать находки проверки через ``checks_config.yaml``.

    Оборачивает ``check_*(root, chapter_number)`` так, что её находки проходят
    через :func:`_apply_config`. ``functools.wraps`` сохраняет ``__name__`` —
    ``verify_chapter`` по-прежнему видит верные имена в ``checks_run``, а
    серверные обёртки одиночных проверок наследуют ту же настройку строгости.
    """

    @functools.wraps(check_fn)
    def wrapper(root: Path, chapter_number: int) -> list[dict[str, Any]]:
        return _apply_config(root, check_fn(root, chapter_number))

    return wrapper


# ─── check_structure ──────────────────────────────────────────────────


@_configurable
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


@_configurable
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


@_configurable
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


# ─── check_patterns ───────────────────────────────────────────────────

# ID паттерна в ячейке таблицы 00_conflicts.md обёрнут в backticks.
_BACKTICK_RE = re.compile(r"`([^`]+)`")


def _pattern_token(cell: str) -> str | None:
    """Достать ID паттерна из ячейки таблицы конфликтов.

    ID — одно слово в backticks (``intro_etymology``). Прозаические
    пометки вроде «(прямая подача нотации)» — не паттерны, вернёт None.
    """
    m = _BACKTICK_RE.search(cell)
    if not m:
        return None
    token = m.group(1).strip()
    if not token or " " in token or token.startswith("("):
        return None
    return token


def _library_pattern_ids(root: Path) -> set[str] | None:
    """Множество ID паттернов в библиотеке ``patterns/`` (по именам файлов).

    Служебные файлы ``00_*`` (индекс, таблица конфликтов) исключаются.
    None — если каталога ``patterns/`` нет (сверять не с чем).
    """
    patterns_root = root / _PATTERNS
    if not patterns_root.is_dir():
        return None
    return {
        md.stem for md in patterns_root.glob("**/*.md") if not md.stem.startswith("00_")
    }


def _is_chapter_scope(level: str) -> bool:
    """Уровень конфликта — «глава» (иначе считаем разделом или тоньше)."""
    return "глав" in level.lower()


def _parse_conflict_pairs(root: Path) -> list[dict[str, str]]:
    """Разобрать таблицы CONFLICT и REDUNDANCY из ``00_conflicts.md``.

    Возвращает список пар ``{p1, p2, relation, level, explanation}``, где
    ``relation`` ∈ {"CONFLICT", "REDUNDANCY"}. Таблица SYNERGY (проза,
    рекомендованные связки) не разбирается — это подсказки, не нарушения.
    Пары, где хотя бы один столбец не настоящий паттерн (прозаическая
    пометка), пропускаются.
    """
    try:
        text = get_conflicts_table(root)
    except ContentNotFoundError:
        return []
    pairs: list[dict[str, str]] = []
    relation: str | None = None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("## "):
            head = s[3:].strip().lower()
            if head.startswith("conflict"):
                relation = "CONFLICT"
            elif head.startswith("redundancy"):
                relation = "REDUNDANCY"
            else:
                relation = None
            continue
        if relation is None or not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) < 3:
            continue
        # строка-разделитель | --- | --- | ...
        if all(re.fullmatch(r":?-+:?", c) for c in cells if c):
            continue
        # строка-заголовок таблицы
        if cells[0].lower().startswith("паттерн"):
            continue
        p1 = _pattern_token(cells[0])
        p2 = _pattern_token(cells[1])
        if p1 is None or p2 is None:
            continue
        explanation = "|".join(cells[3:]).strip() if len(cells) > 3 else ""
        pairs.append(
            {
                "p1": p1,
                "p2": p2,
                "relation": relation,
                "level": cells[2],
                "explanation": explanation,
            }
        )
    return pairs


@_configurable
def check_patterns(root: Path, chapter_number: int) -> list[dict[str, Any]]:
    """Сверить паттерны главы (``patterns_used``) с библиотекой и конфликтами.

    Три находки:

    - ``pattern_unknown`` (warning) — ID паттерна в ``patterns_used``
      какого-то раздела не найден в библиотеке ``patterns/`` (опечатка).
    - ``pattern_conflict`` (warning) — пара из таблицы CONFLICT
      (``00_conflicts.md``) сосуществует: на уровне «глава» — где-либо в
      главе, тоньше — в одном разделе (мельче метаданные не дают).
    - ``pattern_redundancy`` (info) — пара из таблицы REDUNDANCY
      сосуществует (та же логика уровней).

    Жёсткий запрет CONFLICT — забота сборщика (до генерации); здесь, в
    пост-проверке, это warning, а не error: для под-разделных уровней
    («абзац», «задача», «один блок выкладки») совпадение в одном разделе —
    лишь подозрение, не доказанное нарушение.

    Если ``metadata.json`` нет — ``[]`` (как ``check_terms``). Если нет
    каталога ``patterns/`` — тоже ``[]`` (сверять не с чем).

    Args:
        root: корень репозитория.
        chapter_number: номер главы.

    Returns:
        Список находок. Пустой — с паттернами всё в порядке.

    Raises:
        ContentNotFoundError: если файла главы нет (глава не написана).
    """
    _read_chapter(root, chapter_number)  # guard: глава должна быть написана
    check = "check_patterns"

    meta = _load_meta(root, chapter_number)
    if meta is None:
        return []
    valid_ids = _library_pattern_ids(root)
    if valid_ids is None:
        return []

    findings: list[dict[str, Any]] = []

    # Паттерны по разделам и по всей главе.
    section_patterns: list[tuple[int, set[str]]] = []
    chapter_patterns: set[str] = set()
    sections = meta.get("sections")
    if isinstance(sections, list):
        for sec in sections:
            if not isinstance(sec, dict):
                continue
            used = sec.get("patterns_used")
            if not isinstance(used, list):
                continue
            ids = {p.strip() for p in used if isinstance(p, str) and p.strip()}
            num = sec.get("number")
            if isinstance(num, int):
                section_patterns.append((num, ids))
            chapter_patterns |= ids

    # 1) Неизвестные паттерны.
    emitted_unknown: set[tuple[int, str]] = set()
    for num, ids in section_patterns:
        for pid in sorted(ids):
            if pid not in valid_ids and (num, pid) not in emitted_unknown:
                emitted_unknown.add((num, pid))
                findings.append(
                    _finding(
                        check,
                        "warning",
                        "pattern_unknown",
                        f"Паттерн «{pid}» (раздел {num}) не найден в "
                        f"библиотеке patterns/.",
                        location=f"metadata: sections[number={num}].patterns_used",
                    )
                )

    # 2) Конфликты и переигрывания.
    for pair in _parse_conflict_pairs(root):
        p1, p2 = pair["p1"], pair["p2"]
        level = pair["level"]
        expl = pair["explanation"]
        if pair["relation"] == "CONFLICT":
            severity, code, verb = "warning", "pattern_conflict", "конфликтуют"
        else:
            severity, code, verb = "info", "pattern_redundancy", "переигрывают"
        if _is_chapter_scope(level):
            if p1 in chapter_patterns and p2 in chapter_patterns:
                findings.append(
                    _finding(
                        check,
                        severity,
                        code,
                        f"Паттерны «{p1}» и «{p2}» {verb} (уровень «{level}»): {expl}",
                    )
                )
        else:
            for num, ids in section_patterns:
                if p1 in ids and p2 in ids:
                    findings.append(
                        _finding(
                            check,
                            severity,
                            code,
                            f"Паттерны «{p1}» и «{p2}» {verb} в одном разделе "
                            f"(уровень «{level}»): {expl}",
                            location=f"## {num}.",
                        )
                    )

    return findings


# ─── check_promises ───────────────────────────────────────────────────


@_configurable
def check_promises(root: Path, chapter_number: int) -> list[dict[str, Any]]:
    """Сверить обещания мостика прошлой главы с тем, что эта глава подхватила.

    Каждый мостик (``bridge_to_next.promises`` главы N−1) даёт обещания,
    которые глава N должна отработать. На стороне главы N эти обещания
    перечисляются в ``previous_promises_to_fulfill`` плана. Эта проверка
    сверяет **бухгалтерию смежности**, а не семантику прозы:

    - ``promises_not_carried`` (warning) — мостик прошлой главы что-то
      обещал, а в ``previous_promises_to_fulfill`` этой главы пусто (или
      поля нет): обещания «потерялись» между главами.
    - ``promise_count_shortfall`` (info) — глава подхватила меньше
      пунктов, чем обещано мостиком: возможно, часть обещаний забыта.

    Сознательно **без** фаззи/семантической сверки строк: совпадение
    перефразированных русских формулировок без устойчивых ID ненадёжно и
    уводит в LLM-территорию (а сервер детерминированный). Поэтому здесь —
    только счёт и факт наличия.

    Если предыдущей главы нет или она ничего не обещала — ``[]``. Если у
    этой главы нет ``metadata.json`` — тоже ``[]`` (ошибку
    ``missing_metadata`` выдаёт :func:`check_structure`).

    Args:
        root: корень репозитория.
        chapter_number: номер проверяемой главы.

    Returns:
        Список находок. Пустой — обещания смежности в порядке.

    Raises:
        ContentNotFoundError: если файла главы нет (глава не написана).
    """
    _read_chapter(root, chapter_number)  # guard: глава должна быть написана
    check = "check_promises"

    pending = get_pending_promises(root, chapter_number)
    if not pending:
        return []  # нет предыдущей главы / она ничего не обещала

    meta = _load_meta(root, chapter_number)
    if meta is None:
        return []  # missing_metadata — забота check_structure

    carried = meta.get("previous_promises_to_fulfill")
    carried_list = (
        [c for c in carried if isinstance(c, str) and c.strip()]
        if isinstance(carried, list)
        else []
    )

    made_in = pending[0]["made_in_chapter"]
    n_pending = len(pending)
    findings: list[dict[str, Any]] = []

    if not carried_list:
        findings.append(
            _finding(
                check,
                "warning",
                "promises_not_carried",
                f"Глава {made_in} оставила в мостике {n_pending} обещаний, "
                f"но глава {chapter_number} их не подхватила "
                f"(previous_promises_to_fulfill пуст или отсутствует).",
                location="metadata: previous_promises_to_fulfill",
            )
        )
    elif len(carried_list) < n_pending:
        findings.append(
            _finding(
                check,
                "info",
                "promise_count_shortfall",
                f"Глава {made_in} оставила {n_pending} обещаний, а глава "
                f"{chapter_number} перечисляет {len(carried_list)} пунктов в "
                f"previous_promises_to_fulfill — проверьте, все ли подхвачены.",
                location="metadata: previous_promises_to_fulfill",
            )
        )

    return findings


# ─── check_styleguide ─────────────────────────────────────────────────

# Запрещённые конструкции (style_guide.md, §«Запрещённые конструкции»).
# Хардкод осознанный: список редакторский и стабильный, а парсить прозу
# стилгайда хрупко — в одном пункте бывает и запрет, и рекомендованная
# замена («мы знаем, что» → «вы помните, что»), их не различить наивно.
# Отдельные строки — distinctive, риск ложных срабатываний почти нулевой.
_FORBIDDEN_PHRASES = (
    "следует заметить",
    "следует отметить",
    "было бы целесообразно",
    "мы знаем, что",
    "очевидно, что",
    "нетрудно видеть",
)

# Связки-наполнители: контекстно допустимы, поэтому info, а не warning.
# «данный» сознательно НЕ ловим: по подстроке сталкивается с «данные/
# данных» (= data), по границе слова не отличить «данный»=«этот» от
# легитимного — это случай для человека, не для грепа.
_FILLER_WORDS = (
    "является",
    "являются",
)

_FORBIDDEN_RE = tuple(
    (p, re.compile(re.escape(p), re.IGNORECASE)) for p in _FORBIDDEN_PHRASES
)
_FILLER_RE = tuple(
    (w, re.compile(rf"\b{re.escape(w)}\b", re.IGNORECASE)) for w in _FILLER_WORDS
)

# Умножение чисел: между цифрами нужен \cdot, не \times. Регекс
# цифра-\times-цифра не цепляет легитимное «m \times n» (размер матрицы)
# и \times в декартовом произведении.
_TIMES_BETWEEN_NUMBERS = re.compile(r"\d\s*\\times\s*\d")


@_configurable
def check_styleguide(root: Path, chapter_number: int) -> list[dict[str, Any]]:
    """Сверить прозу главы с механически проверяемой частью стилгайда.

    Три находки:

    - ``styleguide_forbidden_phrase`` (warning) — в прозе встретилась
      запрещённая канцелярская конструкция из стоп-списка стилгайда
      («следует заметить», «очевидно, что» и т.п.).
    - ``styleguide_filler_word`` (info) — связка-наполнитель «является»/
      «являются»; стилгайд советует «X — это Y». Контекстно допустима,
      поэтому info.
    - ``styleguide_formula_notation`` (warning) — между числами знак
      умножения записан как ``\\times`` вместо ``\\cdot``.

    Семантические правила стилгайда (активный залог, «человечность» тона,
    «голая» математика без ``$``) **вне охвата**: детерминированно их не
    проверить, а сервер не зовёт LLM. Сверяется только проза — план
    (``metadata.json``) этой проверке не нужен.

    Args:
        root: корень репозитория.
        chapter_number: номер главы.

    Returns:
        Список находок. Пустой — проза чистая по проверяемым правилам.

    Raises:
        ContentNotFoundError: если файла главы нет (глава не написана).
    """
    content, _ = _read_chapter(root, chapter_number)
    check = "check_styleguide"
    findings: list[dict[str, Any]] = []

    for lineno, line in enumerate(content.splitlines(), start=1):
        for phrase, rx in _FORBIDDEN_RE:
            if rx.search(line):
                findings.append(
                    _finding(
                        check,
                        "warning",
                        "styleguide_forbidden_phrase",
                        f"Канцелярит «{phrase}» — стилгайд запрещает эту конструкцию.",
                        location=f"строка {lineno}",
                    )
                )
        for word, rx in _FILLER_RE:
            if rx.search(line):
                findings.append(
                    _finding(
                        check,
                        "info",
                        "styleguide_filler_word",
                        f"«{word}» — связка-наполнитель; стилгайд советует "
                        f"«X — это Y».",
                        location=f"строка {lineno}",
                    )
                )
        if _TIMES_BETWEEN_NUMBERS.search(line):
            findings.append(
                _finding(
                    check,
                    "warning",
                    "styleguide_formula_notation",
                    "Между числами знак умножения — \\cdot, а не \\times.",
                    location=f"строка {lineno}",
                )
            )

    return findings


# ─── check_links ──────────────────────────────────────────────────────

# Markdown-картинка: ![alt](path) — захватываем путь до первого пробела/
# закрывающей скобки (опциональный « "title"» после пути отбрасываем).
_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(\s*([^)\s]+)")

# Ссылка на главу в прозе: «глава/главе/главы/главу/главой N» или «гл. N».
# \b перед «глав», чтобы не цеплять «заглавие» и подобные слова.
_CHAPTER_REF_RE = re.compile(
    r"\bглав(?:а|е|ы|у|ой)\s+(\d+)|\bгл\.\s*(\d+)",
    re.IGNORECASE,
)

# Внешние/нелокальные картинки офлайн проверить нельзя — пропускаем.
_EXTERNAL_IMAGE_PREFIXES = ("http://", "https://", "data:", "//")


@_configurable
def check_links(root: Path, chapter_number: int) -> list[dict[str, Any]]:
    """Сверить ссылки прозы с тем, что реально есть на диске.

    Две находки:

    - ``missing_image`` (error) — Markdown-картинка ``![alt](images/...)``
      ссылается на локальный файл, которого нет на диске (путь берётся
      относительно папки главы). Внешние ссылки (``http(s)://``, ``data:``,
      ``//``) пропускаются — офлайн их не проверить.
    - ``broken_chapter_ref`` (warning) — проза упоминает «главу N» (или
      «гл. N»), а папки ``chapters/chapter_NN`` в репозитории нет. Каждый
      отсутствующий номер — одна находка (по первому упоминанию). Сюда же
      попадают ссылки «вперёд» на ещё не написанные главы.

    Сверяется только проза и файловая система — план (``metadata.json``)
    этой проверке не нужен, поэтому она работает и на черновике без плана.

    Args:
        root: корень репозитория.
        chapter_number: номер главы.

    Returns:
        Список находок. Пустой — все ссылки на месте.

    Raises:
        ContentNotFoundError: если файла главы нет (глава не написана).
    """
    content, _ = _read_chapter(root, chapter_number)
    check = "check_links"
    chapter_dir = _chapter_dir(root, chapter_number)
    findings: list[dict[str, Any]] = []
    seen_missing_chapters: set[int] = set()

    for lineno, line in enumerate(content.splitlines(), start=1):
        # 1) Картинки: существует ли локальный файл.
        for m in _IMAGE_RE.finditer(line):
            path = m.group(1).strip()
            if path.lower().startswith(_EXTERNAL_IMAGE_PREFIXES):
                continue
            if not (chapter_dir / path).is_file():
                findings.append(
                    _finding(
                        check,
                        "error",
                        "missing_image",
                        f"Картинка «{path}» не найдена: ожидался файл "
                        f"{chapter_dir.name}/{path}.",
                        location=f"строка {lineno}",
                    )
                )
        # 2) Ссылки на главы: есть ли папка chapter_NN.
        for m in _CHAPTER_REF_RE.finditer(line):
            num = int(m.group(1) or m.group(2))
            if num in seen_missing_chapters:
                continue
            ref_dir = _chapter_dir(root, num)
            if not ref_dir.is_dir():
                seen_missing_chapters.add(num)
                findings.append(
                    _finding(
                        check,
                        "warning",
                        "broken_chapter_ref",
                        f"Ссылка на главу {num}, но папки {ref_dir.name} "
                        f"в репозитории нет.",
                        location=f"строка {lineno}",
                    )
                )

    return findings


# ─── verify_chapter ───────────────────────────────────────────────────

# Все проверки, которые запускает оркестратор. Расширяется со срезами.
_ALL_CHECKS = (
    check_structure,
    check_markers,
    check_terms,
    check_patterns,
    check_promises,
    check_styleguide,
    check_links,
)


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
              "checks_run": ["check_structure", "check_markers",
                             "check_terms", "check_patterns",
                             "check_promises", "check_styleguide",
                             "check_links"],
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
