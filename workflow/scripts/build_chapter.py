"""build_chapter.py — сборочный пайплайн автора: план → numeric → verify.

Одна команда собирает главу из исходников и проверяет результат:

1. **план**   — читает ``chapters/chapter_NN/metadata.json`` и проверяет, что
   план структурно валиден (``validate_plan``). Любая ошибка плана — это
   гейт: дальше не идём (нечего собирать на битом плане).
2. **numeric** — если рядом есть ``draft.md`` с маркерами ``[NUMERIC: ...]``,
   прогоняет его через ``numeric_executor`` и пишет ``chapter.md`` (математика
   выверяется SymPy). Если ``draft.md`` нет, а ``chapter.md`` уже есть
   (legacy-глава) — стадию numeric пропускаем.
3. **verify**  — прямым импортом зовёт ``verify_tools.verify_chapter`` (9
   проверок Группы B) и сводит находки в общий отчёт.

Находки всех стадий — единый формат ``{check, severity, code, message,
location}``. Итоговый вердикт по той же логике, что у ``verify_chapter``:
``fail`` при любой ошибке, иначе ``warn`` при предупреждении, иначе ``ok``.

Запуск::

    python workflow/scripts/build_chapter.py <N> [--repo-root PATH]
                                             [--json] [--verbose|--quiet]

Коды выхода: 0 — ok, 1 — warn, 2 — fail (в т.ч. битый план или нечего
собирать).

Замечание про импорт: ``numeric_executor`` лежит рядом (``workflow/scripts``),
а ``verify_tools`` — в ``mcp/``. Обе чистые (без LLM/HTTP; numeric использует
SymPy, но это офлайн-инструмент автора, не MCP-сервер), поэтому собираем их в
одном процессе, добавив оба каталога в ``sys.path``.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

# --- Кросс-пакетные импорты: scripts/ (numeric) и mcp/ (verify) в путь. ----- #
_SCRIPTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = _SCRIPTS_DIR.parents[1]  # workflow/scripts -> workflow -> <repo>
_MCP_DIR = REPO_ROOT / "mcp"
for _p in (str(_SCRIPTS_DIR), str(_MCP_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import numeric_executor  # noqa: E402
from tools import verify_tools  # noqa: E402
from tools.context_tools import ContentNotFoundError  # noqa: E402

logger = logging.getLogger("build_chapter")

_PLAN_CHECK = "validate_plan"
_NUMERIC_CHECK = "numeric"
_VERIFY_CHECK = "verify"


# --------------------------------------------------------------------------- #
# Находки                                                                       #
# --------------------------------------------------------------------------- #
def _finding(
    check: str,
    severity: str,
    code: str,
    message: str,
    location: str | None = None,
) -> dict[str, Any]:
    """Собрать находку в формате Группы B."""
    return {
        "check": check,
        "severity": severity,
        "code": code,
        "message": message,
        "location": location,
    }


def _is_int(value: Any) -> bool:
    """True для настоящего int (bool отсекаем — он подкласс int)."""
    return isinstance(value, int) and not isinstance(value, bool)


def _nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


# --------------------------------------------------------------------------- #
# Стадия «план»                                                                #
# --------------------------------------------------------------------------- #
def _chapter_dir(root: Path, chapter_number: int) -> Path:
    return root / "chapters" / f"chapter_{chapter_number:02d}"


def validate_plan(metadata: dict, chapter_number: int) -> list[dict[str, Any]]:
    """Проверить структуру плана ``metadata.json``.

    Возвращает список находок ``check=validate_plan``. Ошибки (``error``) —
    это то, на что опираются проверки Группы B и сборка: без них дальше идти
    нельзя. Отсутствие необязательного ``bridge_to_next`` — ``warning`` (ок
    для последней главы). Необязательные блоки (``new_terms_introduced``,
    ``biohazards_in_chapter``) проверяются, только если присутствуют.
    """
    findings: list[dict[str, Any]] = []

    cn = metadata.get("chapter_number")
    if not _is_int(cn):
        findings.append(
            _finding(
                _PLAN_CHECK,
                "error",
                "plan_missing_chapter_number",
                "metadata.json: поле 'chapter_number' отсутствует или не целое.",
            )
        )
    elif cn != chapter_number:
        findings.append(
            _finding(
                _PLAN_CHECK,
                "warning",
                "plan_chapter_number_mismatch",
                f"metadata.json: 'chapter_number'={cn}, "
                f"а собираем главу {chapter_number}.",
            )
        )

    sections = metadata.get("sections")
    if not isinstance(sections, list) or not sections:
        findings.append(
            _finding(
                _PLAN_CHECK,
                "error",
                "plan_sections_invalid",
                "metadata.json: 'sections' должен быть непустым списком разделов.",
            )
        )
    else:
        for idx, sec in enumerate(sections):
            loc = f"sections[{idx}]"
            if not isinstance(sec, dict):
                findings.append(
                    _finding(
                        _PLAN_CHECK,
                        "error",
                        "plan_section_not_object",
                        f"metadata.json: раздел #{idx + 1} в 'sections' не объект.",
                        location=loc,
                    )
                )
                continue
            if not _is_int(sec.get("number")):
                findings.append(
                    _finding(
                        _PLAN_CHECK,
                        "error",
                        "plan_section_bad_number",
                        f"metadata.json: у раздела #{idx + 1} нет целого 'number'.",
                        location=loc,
                    )
                )
            if not _nonempty_str(sec.get("title")):
                findings.append(
                    _finding(
                        _PLAN_CHECK,
                        "error",
                        "plan_section_bad_title",
                        f"metadata.json: у раздела #{idx + 1} нет непустого 'title'.",
                        location=loc,
                    )
                )

    if "bridge_to_next" not in metadata:
        findings.append(
            _finding(
                _PLAN_CHECK,
                "warning",
                "plan_bridge_absent",
                "metadata.json: нет 'bridge_to_next' (мостик к следующей "
                "главе); это ок только для последней главы книги.",
            )
        )
    else:
        bridge = metadata.get("bridge_to_next")
        if not isinstance(bridge, dict):
            findings.append(
                _finding(
                    _PLAN_CHECK,
                    "error",
                    "plan_bridge_invalid",
                    "metadata.json: 'bridge_to_next' должен быть объектом.",
                    location="bridge_to_next",
                )
            )
        else:
            if not _nonempty_str(bridge.get("summary")):
                findings.append(
                    _finding(
                        _PLAN_CHECK,
                        "error",
                        "plan_bridge_no_summary",
                        "metadata.json: в 'bridge_to_next' нет непустого 'summary'.",
                        location="bridge_to_next",
                    )
                )
            if not isinstance(bridge.get("promises"), list):
                findings.append(
                    _finding(
                        _PLAN_CHECK,
                        "error",
                        "plan_bridge_no_promises",
                        "metadata.json: в 'bridge_to_next' 'promises' должен "
                        "быть списком.",
                        location="bridge_to_next",
                    )
                )

    terms = metadata.get("new_terms_introduced")
    if terms is not None:
        if not isinstance(terms, list):
            findings.append(
                _finding(
                    _PLAN_CHECK,
                    "error",
                    "plan_terms_invalid",
                    "metadata.json: 'new_terms_introduced' должен быть списком.",
                    location="new_terms_introduced",
                )
            )
        else:
            for idx, term in enumerate(terms):
                if (
                    not isinstance(term, dict)
                    or not _nonempty_str(term.get("term"))
                    or not _nonempty_str(term.get("definition"))
                ):
                    findings.append(
                        _finding(
                            _PLAN_CHECK,
                            "error",
                            "plan_term_malformed",
                            f"metadata.json: термин #{idx + 1} должен иметь "
                            "непустые 'term' и 'definition'.",
                            location=f"new_terms_introduced[{idx}]",
                        )
                    )

    bios = metadata.get("biohazards_in_chapter")
    if bios is not None:
        if not isinstance(bios, list):
            findings.append(
                _finding(
                    _PLAN_CHECK,
                    "error",
                    "plan_biohazards_invalid",
                    "metadata.json: 'biohazards_in_chapter' должен быть списком.",
                    location="biohazards_in_chapter",
                )
            )
        else:
            for idx, bio in enumerate(bios):
                if not isinstance(bio, dict) or not _nonempty_str(bio.get("name")):
                    findings.append(
                        _finding(
                            _PLAN_CHECK,
                            "error",
                            "plan_biohazard_malformed",
                            f"metadata.json: биохазард #{idx + 1} должен иметь "
                            "непустое 'name'.",
                            location=f"biohazards_in_chapter[{idx}]",
                        )
                    )

    return findings


def load_plan(
    root: Path, chapter_number: int
) -> tuple[dict | None, list[dict[str, Any]]]:
    """Прочитать и проверить план главы.

    Returns:
        ``(metadata, findings)``. ``metadata`` — ``None``, если файла нет, он
        не читается/не парсится или корень не объект (фатально — собирать
        нечего); тогда в ``findings`` ровно одна ошибка. Иначе ``metadata`` —
        словарь, а ``findings`` — результат :func:`validate_plan`.
    """
    path = _chapter_dir(root, chapter_number) / "metadata.json"
    if not path.is_file():
        return None, [
            _finding(
                _PLAN_CHECK,
                "error",
                "plan_missing_metadata",
                f"Нет файла плана: {path}",
                location=str(path),
            )
        ]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return None, [
            _finding(
                _PLAN_CHECK,
                "error",
                "plan_unreadable",
                f"metadata.json не читается или не парсится: {exc}",
                location=str(path),
            )
        ]
    if not isinstance(data, dict):
        return None, [
            _finding(
                _PLAN_CHECK,
                "error",
                "plan_not_object",
                "metadata.json: корневой элемент должен быть объектом.",
                location=str(path),
            )
        ]
    return data, validate_plan(data, chapter_number)


# --------------------------------------------------------------------------- #
# Стадия «numeric»                                                             #
# --------------------------------------------------------------------------- #
class _CapturingHandler(logging.Handler):
    """Лог-хендлер, копящий записи (ловим ошибки numeric_executor)."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def run_numeric(root: Path, chapter_number: int) -> tuple[bool, list[dict[str, Any]]]:
    """Стадия numeric: ``draft.md`` → ``chapter.md`` через SymPy.

    Returns:
        ``(ran, findings)``. ``ran=True``, если был ``draft.md`` и мы собрали
        ``chapter.md``; ошибки маркеров идут находками ``check=numeric``.
        ``ran=False`` без находок — ``draft.md`` нет, но ``chapter.md`` уже
        есть (legacy, numeric пропущен). ``ran=False`` с ошибкой
        ``numeric_no_source`` — собирать нечего (нет ни того, ни другого).
    """
    cdir = _chapter_dir(root, chapter_number)
    draft = cdir / "draft.md"
    chapter = cdir / "chapter.md"

    if draft.is_file():
        handler = _CapturingHandler()
        handler.setLevel(logging.ERROR)
        ne_logger = logging.getLogger("numeric_executor")
        ne_logger.addHandler(handler)
        try:
            err = numeric_executor.process_file(draft, chapter)
        finally:
            ne_logger.removeHandler(handler)

        findings = [
            _finding(
                _NUMERIC_CHECK,
                "error",
                "numeric_marker_error",
                " ".join(rec.getMessage().split()),
            )
            for rec in handler.records
        ]
        if err and not findings:
            findings.append(
                _finding(
                    _NUMERIC_CHECK,
                    "error",
                    "numeric_marker_error",
                    f"{err} маркер(ов) [NUMERIC] не выполнены "
                    "(см. <!-- ERROR --> в chapter.md).",
                )
            )
        return True, findings

    if chapter.is_file():
        return False, []

    return False, [
        _finding(
            _NUMERIC_CHECK,
            "error",
            "numeric_no_source",
            f"В {cdir} нет ни draft.md, ни chapter.md — собирать нечего.",
            location=str(cdir),
        )
    ]


# --------------------------------------------------------------------------- #
# Оркестратор                                                                  #
# --------------------------------------------------------------------------- #
def _assemble_report(
    chapter_number: int,
    stages: dict[str, Any],
    findings: list[dict[str, Any]],
    *,
    stopped_at: str | None = None,
) -> dict[str, Any]:
    """Свести находки в счётчики и вердикт."""
    counts = {"error": 0, "warning": 0, "info": 0}
    for f in findings:
        sev = f.get("severity")
        if sev in counts:
            counts[sev] += 1
    if counts["error"]:
        verdict = "fail"
    elif counts["warning"]:
        verdict = "warn"
    else:
        verdict = "ok"
    return {
        "chapter_number": chapter_number,
        "stages": stages,
        "findings": findings,
        "counts": counts,
        "verdict": verdict,
        "stopped_at": stopped_at,
    }


def run_build(root: Path, chapter_number: int) -> dict[str, Any]:
    """Собрать главу: план → numeric → verify. Вернуть сводный отчёт.

    Гейты: ошибка плана останавливает до numeric/verify; отсутствие исходника
    (``numeric_no_source``) — до verify. Ошибки маркеров numeric верстку не
    прерывают (verify всё равно запускается, чтобы автор увидел всё за раз),
    но дают итоговый ``fail``.
    """
    stages: dict[str, Any] = {}
    findings: list[dict[str, Any]] = []

    # Стадия 1 — план.
    metadata, plan_findings = load_plan(root, chapter_number)
    stages["plan"] = {"findings": plan_findings}
    findings.extend(plan_findings)
    if any(f["severity"] == "error" for f in plan_findings):
        return _assemble_report(chapter_number, stages, findings, stopped_at="plan")

    # Стадия 2 — numeric.
    ran, numeric_findings = run_numeric(root, chapter_number)
    stages["numeric"] = {"ran": ran, "findings": numeric_findings}
    findings.extend(numeric_findings)
    if any(f["code"] == "numeric_no_source" for f in numeric_findings):
        return _assemble_report(chapter_number, stages, findings, stopped_at="numeric")

    # Стадия 3 — verify.
    try:
        report = verify_tools.verify_chapter(root, chapter_number)
        stages["verify"] = report
        findings.extend(report.get("findings", []))
    except ContentNotFoundError as exc:
        verify_finding = _finding(_VERIFY_CHECK, "error", "verify_no_chapter", str(exc))
        stages["verify"] = {"findings": [verify_finding], "error": str(exc)}
        findings.append(verify_finding)

    return _assemble_report(chapter_number, stages, findings)


# --------------------------------------------------------------------------- #
# Человекочитаемый вывод                                                        #
# --------------------------------------------------------------------------- #
def _severity_counts(findings: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"error": 0, "warning": 0, "info": 0}
    for f in findings:
        sev = f.get("severity")
        if sev in counts:
            counts[sev] += 1
    return counts


def format_report(report: dict[str, Any]) -> str:
    """Собрать человекочитаемую сводку по отчёту :func:`run_build`."""
    lines = [f"=== Сборка главы {report['chapter_number']} ==="]
    stages = report["stages"]

    plan = stages.get("plan")
    if plan is not None:
        c = _severity_counts(plan["findings"])
        if c["error"]:
            lines.append(f"[план]    ОШИБКА — план невалиден ({c['error']} ошибк.)")
        elif c["warning"]:
            lines.append(f"[план]    OK ({c['warning']} предупр.)")
        else:
            lines.append("[план]    OK")

    num = stages.get("numeric")
    if num is not None:
        if num["ran"]:
            ce = _severity_counts(num["findings"])["error"]
            tail = f", ошибок маркеров: {ce}" if ce else ", без ошибок"
            lines.append(f"[numeric] draft.md → chapter.md{tail}")
        elif any(f["code"] == "numeric_no_source" for f in num["findings"]):
            lines.append("[numeric] нечего собирать (нет draft.md и chapter.md)")
        else:
            lines.append("[numeric] draft.md не найден — пропуск (готовый chapter.md)")
    elif report.get("stopped_at") == "plan":
        lines.append("[numeric] не запускался (план невалиден)")

    ver = stages.get("verify")
    if ver is not None:
        c = ver.get("counts")
        if c is not None:
            lines.append(
                f"[verify]  verdict={ver.get('verdict')} "
                f"(errors={c['error']}, warnings={c['warning']}, info={c['info']})"
            )
        else:
            lines.append("[verify]  глава не найдена")
    elif report.get("stopped_at"):
        lines.append("[verify]  не запускался")

    if report["findings"]:
        lines.append("")
        lines.append("Находки:")
        for f in report["findings"]:
            loc = f" ({f['location']})" if f.get("location") else ""
            lines.append(
                f"  - {f['check']:<15} {f['severity']:<7} "
                f"{f['code']}: {f['message']}{loc}"
            )

    lines.append("")
    lines.append(f"Итог: {report['verdict'].upper()}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# CLI                                                                          #
# --------------------------------------------------------------------------- #
_EXIT_CODES = {"ok": 0, "warn": 1, "fail": 2}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="build_chapter.py",
        description="Сборочный пайплайн главы: план → numeric → verify.",
    )
    parser.add_argument("chapter", type=int, help="номер главы")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="корень репозитория (по умолчанию — каталог этого репо)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="вывести сводный отчёт как JSON вместо человекочитаемой сводки",
    )
    verbosity = parser.add_mutually_exclusive_group()
    verbosity.add_argument(
        "--verbose", action="store_true", help="подробный лог (DEBUG)"
    )
    verbosity.add_argument(
        "--quiet", action="store_true", help="только предупреждения (WARNING)"
    )
    return parser


def configure_logging(verbose: bool, quiet: bool) -> None:
    level = logging.INFO
    if verbose:
        level = logging.DEBUG
    elif quiet:
        level = logging.WARNING
    logging.basicConfig(
        level=level, format="[%(levelname)s] %(message)s", encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    configure_logging(args.verbose, args.quiet)

    root: Path = args.repo_root or REPO_ROOT
    report = run_build(root, args.chapter)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(format_report(report))

    return _EXIT_CODES.get(report["verdict"], 2)


if __name__ == "__main__":
    sys.exit(main())
