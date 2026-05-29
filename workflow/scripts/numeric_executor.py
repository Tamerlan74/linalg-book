"""numeric_executor.py — выполнение численных вычислений в главах книги.

Находит в Markdown-тексте маркеры вида ``[NUMERIC: <type>, k=v, ...]``,
выполняет соответствующие вычисления через SymPy (с перекрёстной проверкой
через NumPy) и заменяет каждый маркер на готовую LaTeX-выкладку с числами.

Поддерживаемые типы: ``det``, ``matmul``, ``inverse``, ``vec_op``, ``solve``,
``expand``.

Запуск::

    python scripts/numeric_executor.py <input.md> [--output <output.md>]
                                       [--verbose] [--quiet] [--check]

Коды выхода:
    0 — успех, все маркеры обработаны;
    1 — файл обработан, но хотя бы один маркер дал ошибку;
    2 — фатальная ошибка (файл не найден, не читается и т.п.).
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any

import sympy as sp

logger = logging.getLogger("numeric_executor")


# --------------------------------------------------------------------------- #
# Исключения                                                                   #
# --------------------------------------------------------------------------- #
class NumericError(Exception):
    """Базовое исключение для всех ошибок этого скрипта."""


class MarkerSyntaxError(NumericError):
    """Маркер синтаксически некорректен (не парсится)."""


class UnsupportedTypeError(NumericError):
    """Тип маркера не поддерживается или ещё не реализован."""


class ComputationError(NumericError):
    """Вычисление невозможно (вырожденная матрица, несовместимые размеры)."""


# --------------------------------------------------------------------------- #
# Вспомогательные функции форматирования LaTeX                                 #
# --------------------------------------------------------------------------- #
def to_sympy(value: Any) -> Any:
    """Рекурсивно превращает Python-значение в точное число SymPy.

    Целые остаются Integer, ``float`` превращается в ``Rational`` через строку
    (чтобы 0.5 стало 1/2, а не приближённым Float). Списки обрабатываются
    поэлементно.

    Вход: 2, 0.5, [[2, 0], [1, 3]].
    Выход: Integer(2), Rational(1, 2), вложенный список sympy-чисел.
    """
    if isinstance(value, bool):  # bool — подкласс int, отсекаем явно
        raise MarkerSyntaxError(f"boolean is not a valid number: {value!r}")
    if isinstance(value, int):
        return sp.Integer(value)
    if isinstance(value, float):
        return sp.Rational(str(value))
    if isinstance(value, (list, tuple)):
        return [to_sympy(v) for v in value]
    raise MarkerSyntaxError(f"cannot interpret value as number: {value!r}")


def fmt_num(x: Any) -> str:
    """Форматирует одно число SymPy в LaTeX.

    Целые — как есть (``6``), рациональные — через ``\\frac`` со знаком впереди
    (``-\\frac{1}{2}``), корни и прочее — через ``sympy.latex``.

    Вход: Integer(6), Rational(9, 5), Rational(-1, 2).
    Выход: "6", "\\frac{9}{5}", "-\\frac{1}{2}".
    """
    x = sp.sympify(x)
    if x.is_Integer:
        return str(int(x))
    if x.is_Rational:
        p, q = x.p, x.q
        if q == 1:
            return str(p)
        sign = "-" if x < 0 else ""
        return f"{sign}\\frac{{{abs(p)}}}{{{q}}}"
    return sp.latex(x)


def matrix_to_pmatrix(M: sp.Matrix) -> str:
    """Превращает sympy.Matrix в LaTeX ``\\begin{pmatrix} ... \\end{pmatrix}``.

    Вход: Matrix([[2, 0], [1, 3]]).
    Выход: "\\begin{pmatrix} 2 & 0 \\\\ 1 & 3 \\end{pmatrix}".
    """
    rows = [
        " & ".join(fmt_num(M[i, j]) for j in range(M.cols))
        for i in range(M.rows)
    ]
    body = " \\\\ ".join(rows)
    return r"\begin{pmatrix} " + body + r" \end{pmatrix}"


def vector_to_pmatrix(v: list) -> str:
    """Форматирует вектор как столбец ``\\begin{pmatrix} a \\\\ b \\end{pmatrix}``.

    Вход: [Integer(6), Integer(2)].
    Выход: "\\begin{pmatrix} 6 \\\\ 2 \\end{pmatrix}".
    """
    body = " \\\\ ".join(fmt_num(c) for c in v)
    return r"\begin{pmatrix} " + body + r" \end{pmatrix}"


def wrap(latex: str, *, display: str | None = None) -> str:
    """Оборачивает LaTeX в ``$...$`` (инлайн) или ``$$...$$`` (блок).

    Если ``display`` задан явно ("inline"/"block") — используется он. Иначе
    режим выбирает вызывающая execute-функция, передавая готовый флаг через
    ``display``. Эта функция только оборачивает.
    """
    if display == "block":
        return f"$$ {latex} $$"
    return f"${latex}$"


# --------------------------------------------------------------------------- #
# Парсер маркеров                                                              #
# --------------------------------------------------------------------------- #
_OPENERS = {"[": "]", "(": ")", "{": "}"}
_CLOSERS = {"]": "[", ")": "(", "}": "{"}


def _split_top_level(text: str, sep: str = ",") -> list[str]:
    """Разбивает строку по ``sep`` только на верхнем уровне вложенности.

    Запятые внутри ``[...]``, ``(...)`` или ``{...}`` не считаются
    разделителями. Кавычки тоже учитываются (внутри кавычек ничего не делим).

    Вход: 'det, A=[[2,0],[1,3]]'.
    Выход: ['det', 'A=[[2,0],[1,3]]'].
    """
    parts: list[str] = []
    depth = 0
    in_quote = False
    buf: list[str] = []
    for ch in text:
        if ch == '"':
            in_quote = not in_quote
            buf.append(ch)
        elif in_quote:
            buf.append(ch)
        elif ch in _OPENERS:
            depth += 1
            buf.append(ch)
        elif ch in _CLOSERS:
            depth -= 1
            if depth < 0:
                raise MarkerSyntaxError(f"unbalanced brackets in: {text!r}")
            buf.append(ch)
        elif ch == sep and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if depth != 0 or in_quote:
        raise MarkerSyntaxError(f"unbalanced brackets/quotes in: {text!r}")
    parts.append("".join(buf))
    return parts


def _parse_value(raw: str) -> Any:
    """Парсит значение параметра маркера.

    Числа, списки и вложенные списки парсятся через ``ast.literal_eval``.
    Голые идентификаторы (``add``, ``identity``) и выражения (``(a+b)*(c+d)``)
    остаются строками.
    """
    import ast

    raw = raw.strip()
    try:
        return ast.literal_eval(raw)
    except (ValueError, SyntaxError):
        return raw


def parse_marker(marker_text: str) -> dict:
    """Парсит строку маркера и возвращает словарь параметров.

    Ведущий префикс ``NUMERIC:`` опционален. Пробелы и переводы строк вокруг
    ``=`` и ``,`` допускаются; внутри значений (``[[...]]``) — нет.

    Вход: 'NUMERIC: det, A=[[2,0],[1,3]]'.
    Выход: {'type': 'det', 'A': [[2, 0], [1, 3]]}.

    Raises:
        MarkerSyntaxError: если синтаксис маркера неверный.
    """
    text = marker_text.strip()
    if text.upper().startswith("NUMERIC:"):
        text = text[len("NUMERIC:"):].strip()
    # Переносы строк внутри маркера превращаем в пробелы.
    text = " ".join(text.split())
    if not text:
        raise MarkerSyntaxError("empty marker")

    segments = _split_top_level(text, ",")
    type_token = segments[0].strip()
    if not type_token or "=" in type_token:
        raise MarkerSyntaxError(
            f"marker must start with a type token (no '='): {marker_text!r}"
        )

    parsed: dict[str, Any] = {"type": type_token}
    for seg in segments[1:]:
        seg = seg.strip()
        if not seg:
            continue
        if "=" not in seg:
            raise MarkerSyntaxError(
                f"parameter without '=' in marker: {seg!r}"
            )
        key, raw_val = seg.split("=", 1)
        key = key.strip()
        if not key:
            raise MarkerSyntaxError(f"empty parameter name in: {seg!r}")
        parsed[key] = _parse_value(raw_val)
    return parsed


def _require(parsed: dict, key: str, marker_type: str) -> Any:
    """Достаёт обязательный параметр или бросает понятную ошибку."""
    if key not in parsed:
        raise MarkerSyntaxError(
            f"marker '{marker_type}' requires parameter '{key}'"
        )
    return parsed[key]


def _as_matrix(value: Any, name: str) -> sp.Matrix:
    """Превращает распарсенное значение в sympy.Matrix с проверкой формы."""
    if not isinstance(value, (list, tuple)) or not value:
        raise MarkerSyntaxError(f"parameter '{name}' must be a matrix [[...]]")
    if not all(isinstance(row, (list, tuple)) for row in value):
        raise MarkerSyntaxError(
            f"parameter '{name}' must be a matrix of rows, got {value!r}"
        )
    widths = {len(row) for row in value}
    if len(widths) != 1:
        raise ComputationError(
            f"matrix '{name}' has rows of unequal length: {value!r}"
        )
    return sp.Matrix(to_sympy([list(r) for r in value]))


# --------------------------------------------------------------------------- #
# Численная перекрёстная проверка (NumPy)                                      #
# --------------------------------------------------------------------------- #
def _numpy_det(M: sp.Matrix) -> float | None:
    """Считает det через numpy для sanity-check. None, если numpy недоступен."""
    try:
        import numpy as np
    except ImportError:  # pragma: no cover - numpy в зависимостях
        logger.debug("numpy not available, skipping numeric cross-check")
        return None
    arr = np.array(M.tolist(), dtype=float)
    return float(np.linalg.det(arr))


def _check_close(symbolic_value: Any, numeric_value: float | None,
                 *, context: str, tol: float = 1e-6) -> None:
    """Сравнивает точное значение SymPy с приближённым из NumPy."""
    if numeric_value is None:
        return
    exact = float(sp.sympify(symbolic_value))
    if abs(exact - numeric_value) > tol:
        raise ComputationError(
            f"sanity check failed for {context}: "
            f"symbolic={exact}, numeric={numeric_value}"
        )


# --------------------------------------------------------------------------- #
# Реализации вычислений                                                        #
# --------------------------------------------------------------------------- #
def execute_det(A: list[list]) -> str:
    """Вычисляет определитель и возвращает LaTeX с раскладкой.

    2×2 — явная формула ``ad - bc`` (инлайн). 3×3 — разложение по первой строке
    с независимой сверкой (блок). 4×4 и больше — только итог.

    Вход: [[2, 0], [1, 3]].
    Выход: "$\\det \\begin{pmatrix} 2 & 0 \\\\ 1 & 3 \\end{pmatrix} = ... = 6$".

    Raises:
        ComputationError: если матрица не квадратная или sanity check не сошёлся.
    """
    M = _as_matrix(A, "A")
    if M.rows != M.cols:
        raise ComputationError(
            f"cannot compute determinant of non-square matrix "
            f"{M.rows}x{M.cols}"
        )
    n = M.rows
    value = M.det()
    _check_close(value, _numpy_det(M), context="det")
    pm = matrix_to_pmatrix(M)

    if n == 1:
        return wrap(f"\\det {pm} = {fmt_num(M[0, 0])}")

    if n == 2:
        a, b, c, d = M[0, 0], M[0, 1], M[1, 0], M[1, 1]
        expr = (
            f"\\det {pm} = {fmt_num(a)} \\cdot {fmt_num(d)} - "
            f"{fmt_num(b)} \\cdot {fmt_num(c)} = {fmt_num(value)}"
        )
        return wrap(expr)

    if n == 3:
        # Разложение по первой строке: a11*M11 - a12*M12 + a13*M13.
        terms_minor = []   # \det(minor) с подматрицами
        terms_value = []   # числовые значения миноров
        for j in range(3):
            minor = M.minor_submatrix(0, j)
            minor_det = minor.det()
            sign = "+" if j != 1 else "-"
            terms_minor.append(
                f"{sign} {fmt_num(M[0, j])} \\cdot \\det "
                f"{matrix_to_pmatrix(minor)}"
            )
            terms_value.append(
                f"{sign} {fmt_num(M[0, j])} \\cdot ({fmt_num(minor_det)})"
            )
        minors_str = " ".join(terms_minor).lstrip("+ ").strip()
        values_str = " ".join(terms_value).lstrip("+ ").strip()
        expr = (
            f"\\det {pm} = {minors_str} = {values_str} = {fmt_num(value)}"
        )
        return wrap(expr, display="block")

    # 4×4 и больше — только итог.
    return wrap(f"\\det {pm} = {fmt_num(value)}", display="block")


def execute_matmul(A: list[list], B: list[list],
                   format: str | None = None) -> str:  # noqa: A002
    """Умножение BA (сначала A, потом B) с проверками.

    Для 2×2 без ``format=result_only`` показывает поэлементную выкладку.
    Для больших матриц или ``format=result_only`` — только итоговая матрица.

    Вход: A=[[2,0],[1,3]], B=[[1,4],[0,2]].
    Выход: "$$BA = \\begin{pmatrix} ... \\end{pmatrix} = ...$$".

    Raises:
        ComputationError: если размеры несовместимы или sanity check не сошёлся.
    """
    MA = _as_matrix(A, "A")
    MB = _as_matrix(B, "B")
    # BA = B * A: B это p×q, A это m×n, нужно q == m.
    if MB.cols != MA.rows:
        raise ComputationError(
            f"incompatible sizes for product BA: B is {MB.rows}x{MB.cols}, "
            f"A is {MA.rows}x{MA.cols}; need B.cols == A.rows "
            f"({MB.cols} != {MA.rows})"
        )
    result = MB * MA

    # Sanity check через определители (только для квадратных).
    if MA.rows == MA.cols and MB.rows == MB.cols and MA.rows == MB.rows:
        lhs = result.det()
        rhs = MB.det() * MA.det()
        if sp.simplify(lhs - rhs) != 0:
            raise ComputationError(
                f"sanity check failed: det(BA)={lhs} != "
                f"det(B)*det(A)={rhs}"
            )

    result_pm = matrix_to_pmatrix(result)

    if format == "result_only" or not (MB.rows == 2 and MA.cols == 2
                                        and MB.cols == 2):
        return wrap(f"BA = {result_pm}", display="block")

    # Поэлементная выкладка для 2×2.
    entry_rows = []
    for i in range(MB.rows):
        entries = []
        for j in range(MA.cols):
            products = [
                f"{fmt_num(MB[i, k])} \\cdot {fmt_num(MA[k, j])}"
                for k in range(MB.cols)
            ]
            entries.append(" + ".join(products))
        entry_rows.append(" & ".join(entries))
    expansion = (r"\begin{pmatrix} " + " \\\\ ".join(entry_rows)
                 + r" \end{pmatrix}")
    return wrap(f"BA = {expansion} = {result_pm}", display="block")


def execute_inverse(A: list[list]) -> str:
    """Обратная матрица 2×2 с sanity-check ``A·A^{-1} = I``.

    Вход: [[2, 1], [1, 1]].
    Выход: "$$A^{-1} = \\frac{1}{\\det A} ... = \\begin{pmatrix} ... \\end{pmatrix}$$".

    Raises:
        ComputationError: если матрица вырождена.
        UnsupportedTypeError: для матриц больше 2×2 (пока не реализовано).
    """
    M = _as_matrix(A, "A")
    if M.rows != M.cols:
        raise ComputationError(
            f"cannot invert non-square matrix {M.rows}x{M.cols}"
        )
    det = M.det()
    if det == 0:
        raise ComputationError("matrix is singular, no inverse exists")

    if M.rows != 2:
        raise UnsupportedTypeError(
            f"inverse is only implemented for 2x2 matrices, got "
            f"{M.rows}x{M.cols} (not yet implemented)"
        )

    a, b, c, d = M[0, 0], M[0, 1], M[1, 0], M[1, 1]
    inv = M.inv()
    if inv * M != sp.eye(2):
        raise ComputationError("sanity check failed: A * A^{-1} != I")

    adj = sp.Matrix([[d, -b], [-c, a]])
    expr = (
        f"A^{{-1}} = \\frac{{1}}{{\\det A}} {matrix_to_pmatrix(adj)} = "
        f"\\frac{{1}}{{{fmt_num(det)}}} {matrix_to_pmatrix(adj)} = "
        f"{matrix_to_pmatrix(inv)}"
    )
    return wrap(expr, display="block")


def execute_vec_op(v: list, op: str, w: list | None = None,
                   k: Any = None) -> str:
    """Операции с векторами: add, subtract, scale, dot, norm, identity.

    Вход: v=[3,2], op=add, w=[1,4].
    Выход: "$\\vec{v} + \\vec{w} = ... = \\begin{pmatrix} 4 \\\\ 6 \\end{pmatrix}$".

    Raises:
        MarkerSyntaxError: если не хватает параметров для операции.
        UnsupportedTypeError: если операция неизвестна.
    """
    if not isinstance(v, (list, tuple)):
        raise MarkerSyntaxError("parameter 'v' must be a vector [a,b,...]")
    vv = to_sympy(list(v))

    if op == "identity":
        return wrap(vector_to_pmatrix(vv))

    if op == "scale":
        if k is None:
            raise MarkerSyntaxError("op=scale requires parameter 'k'")
        ks = to_sympy(k)
        res = [ks * c for c in vv]
        expr = (
            f"{fmt_num(ks)} \\cdot {vector_to_pmatrix(vv)} = "
            f"{vector_to_pmatrix(res)}"
        )
        return wrap(expr)

    if op == "norm":
        sq = sum(c * c for c in vv)
        norm = sp.sqrt(sq)
        inner = " + ".join(f"{fmt_num(c)}^2" for c in vv)
        expr = (
            f"\\|\\vec{{v}}\\| = \\sqrt{{{inner}}} = "
            f"\\sqrt{{{fmt_num(sq)}}} = {sp.latex(norm)}"
        )
        return wrap(expr)

    # Бинарные операции требуют второй вектор.
    if op in {"add", "subtract", "dot"}:
        if not isinstance(w, (list, tuple)):
            raise MarkerSyntaxError(f"op={op} requires vector parameter 'w'")
        ww = to_sympy(list(w))
        if len(ww) != len(vv):
            raise ComputationError(
                f"vectors have different lengths: {len(vv)} vs {len(ww)}"
            )
        if op == "add":
            res = [a + b for a, b in zip(vv, ww)]
            sign = "+"
        elif op == "subtract":
            res = [a - b for a, b in zip(vv, ww)]
            sign = "-"
        else:  # dot
            dot = sum(a * b for a, b in zip(vv, ww))
            terms = " + ".join(
                f"{fmt_num(a)} \\cdot {fmt_num(b)}"
                for a, b in zip(vv, ww)
            )
            expr = (
                f"\\vec{{v}} \\cdot \\vec{{w}} = {terms} = {fmt_num(dot)}"
            )
            return wrap(expr)
        expr = (
            f"\\vec{{v}} {sign} \\vec{{w}} = {vector_to_pmatrix(vv)} {sign} "
            f"{vector_to_pmatrix(ww)} = {vector_to_pmatrix(res)}"
        )
        return wrap(expr)

    raise UnsupportedTypeError(f"unknown vector operation: {op!r}")


def execute_solve(A: list[list], b: list) -> str:
    """Решение СЛАУ методом Крамера с sanity-check ``A·x = b``.

    Вход: A=[[2,1],[1,3]], b=[5,6].
    Выход: "Решая систему методом Крамера: $x_1 = ... = \\frac{9}{5}$, ...".

    Raises:
        ComputationError: если det A = 0 или система несовместна.
    """
    M = _as_matrix(A, "A")
    if M.rows != M.cols:
        raise ComputationError(
            f"system matrix must be square, got {M.rows}x{M.cols}"
        )
    if not isinstance(b, (list, tuple)) or len(b) != M.rows:
        raise MarkerSyntaxError(
            f"parameter 'b' must be a vector of length {M.rows}"
        )
    bv = sp.Matrix(to_sympy(list(b)))
    det = M.det()
    if det == 0:
        raise ComputationError(
            "system has no unique solution (det A = 0)"
        )

    pieces = []
    solution = []
    for i in range(M.cols):
        Ai = M.copy()
        Ai[:, i] = bv
        det_i = Ai.det()
        xi = sp.Rational(det_i, det)
        solution.append(xi)
        pieces.append(
            f"x_{i + 1} = \\frac{{\\det A_{i + 1}}}{{\\det A}} = "
            f"\\frac{{{fmt_num(det_i)}}}{{{fmt_num(det)}}} = {fmt_num(xi)}"
        )

    # Sanity check: A * x == b.
    x_vec = sp.Matrix(solution)
    if sp.simplify(M * x_vec - bv) != sp.zeros(M.rows, 1):
        raise ComputationError("sanity check failed: A * x != b")

    inner = ", ".join(f"${p}$" for p in pieces)
    return f"Решая систему методом Крамера: {inner}."


def execute_expand(expr: str) -> str:
    """Символьно раскрывает алгебраическое выражение через SymPy.

    Вход: '(a+b)*(c+d)'.
    Выход: "$ac + ad + bc + bd$".

    Raises:
        MarkerSyntaxError: если выражение не парсится SymPy.
    """
    if not isinstance(expr, str):
        raise MarkerSyntaxError("parameter 'expr' must be an expression string")
    try:
        symbolic = sp.sympify(expr)
    except (sp.SympifyError, SyntaxError, TypeError) as exc:
        raise MarkerSyntaxError(
            f"cannot parse expression {expr!r}: {exc}"
        ) from exc
    expanded = sp.expand(symbolic)
    return wrap(sp.latex(expanded))


# --------------------------------------------------------------------------- #
# Диспетчер                                                                     #
# --------------------------------------------------------------------------- #
def execute_marker(parsed: dict) -> str:
    """Выполняет вычисление по распарсенному маркеру и возвращает LaTeX.

    Делегирует специализированным функциям по полю ``type``.

    Raises:
        ComputationError: если вычисление невозможно.
        UnsupportedTypeError: если тип маркера не поддерживается.
        MarkerSyntaxError: если не хватает обязательных параметров.
    """
    marker_type = parsed.get("type")
    match marker_type:
        case "det":
            return execute_det(_require(parsed, "A", "det"))
        case "matmul":
            return execute_matmul(
                _require(parsed, "A", "matmul"),
                _require(parsed, "B", "matmul"),
                format=parsed.get("format"),
            )
        case "inverse":
            return execute_inverse(_require(parsed, "A", "inverse"))
        case "vec_op":
            return execute_vec_op(
                _require(parsed, "v", "vec_op"),
                _require(parsed, "op", "vec_op"),
                w=parsed.get("w"),
                k=parsed.get("k"),
            )
        case "solve":
            return execute_solve(
                _require(parsed, "A", "solve"),
                _require(parsed, "b", "solve"),
            )
        case "expand":
            return execute_expand(_require(parsed, "expr", "expand"))
        case _:
            raise UnsupportedTypeError(
                f"unsupported marker type: {marker_type!r} (not yet implemented)"
            )


# --------------------------------------------------------------------------- #
# Поиск маркеров в тексте (учёт вложенных скобок)                              #
# --------------------------------------------------------------------------- #
def find_markers(text: str) -> list[tuple[int, int, str, int]]:
    """Находит все маркеры ``[NUMERIC: ...]`` с учётом вложенных ``[]``.

    Возвращает список кортежей (start, end, inner_text, line_number), где
    start/end — позиции в тексте (end эксклюзивный), inner_text — содержимое
    без внешних скобок, line_number — номер строки (с 1) начала маркера.
    """
    markers: list[tuple[int, int, str, int]] = []
    needle = "[NUMERIC:"
    i = 0
    while True:
        start = text.find(needle, i)
        if start == -1:
            break
        depth = 0
        j = start
        while j < len(text):
            if text[j] == "[":
                depth += 1
            elif text[j] == "]":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        if depth != 0:
            # Незакрытый маркер — сообщаем и прекращаем поиск.
            line = text.count("\n", 0, start) + 1
            logger.error("line %d: unclosed [NUMERIC: marker", line)
            break
        inner = text[start + 1:j]  # без внешних [ ]
        line = text.count("\n", 0, start) + 1
        markers.append((start, j + 1, inner, line))
        i = j + 1
    return markers


# --------------------------------------------------------------------------- #
# Обработка файла                                                              #
# --------------------------------------------------------------------------- #
def process_text(text: str, *, source_name: str = "<input>",
                 check_only: bool = False) -> tuple[str, int, int]:
    """Обрабатывает текст: находит маркеры, выполняет, заменяет.

    Возвращает (новый_текст, число_успехов, число_ошибок). При ошибке в маркере
    он не заменяется, рядом вставляется HTML-комментарий с описанием.
    """
    markers = find_markers(text)
    logger.info("%s: found %d [NUMERIC] marker(s)", source_name, len(markers))

    ok_count = 0
    err_count = 0
    out = []
    cursor = 0
    for start, end, inner, line in markers:
        out.append(text[cursor:start])
        original = text[start:end]
        try:
            parsed = parse_marker(inner)
            logger.debug("line %d: parsed %s", line, parsed)
            if check_only:
                logger.info("line %d: OK (would compute) - %s",
                            line, parsed.get("type"))
                out.append(original)
                ok_count += 1
            else:
                result = execute_marker(parsed)
                logger.debug("line %d: -> %s", line, result)
                out.append(result)
                ok_count += 1
        except NumericError as exc:
            err_count += 1
            logger.error("%s line %d: %s\n    marker: %s",
                         source_name, line, exc, original.strip())
            # Маркер не заменяем, добавляем комментарий с ошибкой.
            out.append(original)
            out.append(f"\n<!-- ERROR: {exc} -->")
        cursor = end
    out.append(text[cursor:])
    return "".join(out), ok_count, err_count


def process_file(input_path: Path, output_path: Path,
                 *, check_only: bool = False) -> int:
    """Обрабатывает файл целиком и сохраняет результат.

    Возвращает число ошибок (0 — всё хорошо). В режиме ``check_only`` ничего
    не сохраняет.

    Raises:
        FileNotFoundError: если входной файл не существует.
    """
    if not input_path.is_file():
        raise FileNotFoundError(f"input file not found: {input_path}")

    text = input_path.read_text(encoding="utf-8")
    new_text, ok, err = process_text(
        text, source_name=str(input_path), check_only=check_only
    )

    logger.info("%s: %d processed, %d error(s)", input_path.name, ok, err)

    if check_only:
        logger.info("--check mode: no file written")
        return err

    output_path.write_text(new_text, encoding="utf-8")
    logger.info("wrote %s (%d bytes)",
                output_path, len(new_text.encode("utf-8")))
    return err


# --------------------------------------------------------------------------- #
# CLI                                                                          #
# --------------------------------------------------------------------------- #
def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="numeric_executor.py",
        description="Выполняет [NUMERIC: ...] маркеры в Markdown-главе через "
                    "SymPy и заменяет их на LaTeX-выкладки.",
    )
    parser.add_argument("input", type=Path, help="путь к draft.md")
    parser.add_argument(
        "--output", type=Path, default=None,
        help="куда сохранить результат (по умолчанию: chapter.md рядом с input)",
    )
    parser.add_argument(
        "--check", action="store_true",
        help="режим проверки: показать найденные маркеры без сохранения",
    )
    verbosity = parser.add_mutually_exclusive_group()
    verbosity.add_argument(
        "--verbose", action="store_true", help="подробный лог (DEBUG)",
    )
    verbosity.add_argument(
        "--quiet", action="store_true", help="только предупреждения (WARNING)",
    )
    return parser


def configure_logging(verbose: bool, quiet: bool) -> None:
    level = logging.INFO
    if verbose:
        level = logging.DEBUG
    elif quiet:
        level = logging.WARNING
    logging.basicConfig(
        level=level,
        format="[%(levelname)s] %(message)s",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    configure_logging(args.verbose, args.quiet)

    input_path: Path = args.input
    output_path: Path = args.output or (input_path.parent / "chapter.md")

    try:
        errors = process_file(input_path, output_path, check_only=args.check)
    except FileNotFoundError as exc:
        logger.error("%s", exc)
        return 2
    except OSError as exc:
        logger.error("I/O error: %s", exc)
        return 2

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
