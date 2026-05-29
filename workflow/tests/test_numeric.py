"""Тесты для numeric_executor.py."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Делаем scripts/ импортируемым.
SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import numeric_executor as ne  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


# --------------------------------------------------------------------------- #
# Парсинг маркеров                                                             #
# --------------------------------------------------------------------------- #
def test_parse_basic():
    parsed = ne.parse_marker("NUMERIC: det, A=[[2,0],[1,3]]")
    assert parsed == {"type": "det", "A": [[2, 0], [1, 3]]}


def test_parse_without_prefix():
    parsed = ne.parse_marker("det, A=[[2,0],[1,3]]")
    assert parsed["type"] == "det"


def test_parse_spaces_around_eq_and_comma():
    parsed = ne.parse_marker("matmul ,  A = [[2,0],[1,3]] ,  B = [[1,4],[0,2]]")
    assert parsed["type"] == "matmul"
    assert parsed["A"] == [[2, 0], [1, 3]]
    assert parsed["B"] == [[1, 4], [0, 2]]


def test_parse_multiline():
    text = "matmul,\n  A=[[1,0],[0,1]],\n  B=[[2,0],[0,2]]"
    parsed = ne.parse_marker(text)
    assert parsed["A"] == [[1, 0], [0, 1]]


def test_parse_bare_identifier_value():
    parsed = ne.parse_marker("vec_op, v=[3,2], op=add, w=[1,4]")
    assert parsed["op"] == "add"


def test_parse_bad_syntax_raises():
    with pytest.raises(ne.MarkerSyntaxError):
        ne.parse_marker("det A=[[1,2]]")  # параметр без '='
    with pytest.raises(ne.MarkerSyntaxError):
        ne.parse_marker("=foo")  # type с '='


# --------------------------------------------------------------------------- #
# Определитель                                                                 #
# --------------------------------------------------------------------------- #
def test_det_2x2_positive():
    out = ne.execute_det([[2, 0], [1, 3]])
    assert out == (
        "$\\det \\begin{pmatrix} 2 & 0 \\\\ 1 & 3 \\end{pmatrix} = "
        "2 \\cdot 3 - 0 \\cdot 1 = 6$"
    )


def test_det_2x2_negative():
    out = ne.execute_det([[1, 2], [3, 4]])
    assert out.endswith("= -2$")


def test_det_2x2_zero():
    out = ne.execute_det([[2, 4], [1, 2]])
    assert out.endswith("= 0$")


def test_det_3x3_block_and_value():
    # det([[1,2,3],[4,5,6],[7,8,10]]) = -3
    out = ne.execute_det([[1, 2, 3], [4, 5, 6], [7, 8, 10]])
    assert out.startswith("$$") and out.endswith("$$")
    assert out.rstrip("$ ").endswith("-3")


def test_det_non_square_raises():
    with pytest.raises(ne.ComputationError) as exc:
        ne.execute_det([[1, 2, 3]])
    assert "non-square" in str(exc.value)


# --------------------------------------------------------------------------- #
# Умножение матриц                                                            #
# --------------------------------------------------------------------------- #
def test_matmul_2x2_matches_gold_standard():
    out = ne.execute_matmul([[2, 0], [1, 3]], [[1, 4], [0, 2]])
    expected = (
        "$$ BA = \\begin{pmatrix} 1 \\cdot 2 + 4 \\cdot 1 & "
        "1 \\cdot 0 + 4 \\cdot 3 \\\\ 0 \\cdot 2 + 2 \\cdot 1 & "
        "0 \\cdot 0 + 2 \\cdot 3 \\end{pmatrix} = "
        "\\begin{pmatrix} 6 & 12 \\\\ 2 & 6 \\end{pmatrix} $$"
    )
    assert out == expected


def test_matmul_3x3_result_only():
    # Из Части 3, раздел 6: BA должно быть [[2,0,4],[0,3,0],[1,1,1]].
    out = ne.execute_matmul(
        [[1, 0, 2], [0, 1, 0], [1, 1, 1]],
        [[2, 0, 0], [0, 3, 0], [0, 0, 1]],
    )
    assert "\\begin{pmatrix} 2 & 0 & 4" in out
    assert "\\cdot" not in out  # без поэлементной раскладки


def test_matmul_format_result_only():
    out = ne.execute_matmul(
        [[2, 0], [1, 3]], [[1, 4], [0, 2]], format="result_only"
    )
    assert "\\cdot" not in out
    assert "\\begin{pmatrix} 6 & 12 \\\\ 2 & 6 \\end{pmatrix}" in out


def test_matmul_incompatible_raises():
    with pytest.raises(ne.ComputationError) as exc:
        ne.execute_matmul([[1, 2, 3]], [[1, 2], [3, 4]])
    assert "incompatible" in str(exc.value)


def test_matmul_non_commutative():
    ba = ne.execute_matmul([[2, 0], [1, 3]], [[1, 4], [0, 2]])
    ab = ne.execute_matmul([[1, 4], [0, 2]], [[2, 0], [1, 3]])
    assert ba != ab


# --------------------------------------------------------------------------- #
# Обратная матрица                                                            #
# --------------------------------------------------------------------------- #
def test_inverse_regular():
    out = ne.execute_inverse([[2, 1], [1, 1]])
    assert "\\begin{pmatrix} 1 & -1 \\\\ -1 & 2 \\end{pmatrix}" in out


def test_inverse_singular_raises():
    with pytest.raises(ne.ComputationError) as exc:
        ne.execute_inverse([[2, 4], [1, 2]])
    assert "singular" in str(exc.value)


def test_inverse_3x3_not_implemented():
    with pytest.raises(ne.UnsupportedTypeError):
        ne.execute_inverse([[1, 0, 0], [0, 1, 0], [0, 0, 1]])


# --------------------------------------------------------------------------- #
# Векторные операции                                                          #
# --------------------------------------------------------------------------- #
def test_vec_op_add():
    out = ne.execute_vec_op([3, 2], "add", w=[1, 4])
    assert "\\begin{pmatrix} 4 \\\\ 6 \\end{pmatrix}" in out


def test_vec_op_dot():
    out = ne.execute_vec_op([3, 2], "dot", w=[1, 4])
    assert out.endswith("= 11$")


def test_vec_op_scale():
    out = ne.execute_vec_op([3, 2], "scale", k=2)
    assert "\\begin{pmatrix} 6 \\\\ 4 \\end{pmatrix}" in out


def test_vec_op_norm():
    out = ne.execute_vec_op([3, 4], "norm")
    assert out.endswith("= 5$")


def test_vec_op_identity():
    out = ne.execute_vec_op([6, 2], "identity")
    assert out == "$\\begin{pmatrix} 6 \\\\ 2 \\end{pmatrix}$"


# --------------------------------------------------------------------------- #
# СЛАУ                                                                         #
# --------------------------------------------------------------------------- #
def test_solve_unique():
    out = ne.execute_solve([[2, 1], [1, 3]], [5, 6])
    assert "\\frac{9}{5}" in out
    assert "\\frac{7}{5}" in out


def test_solve_singular_raises():
    with pytest.raises(ne.ComputationError) as exc:
        ne.execute_solve([[1, 1], [2, 2]], [1, 2])
    assert "det A = 0" in str(exc.value)


# --------------------------------------------------------------------------- #
# expand                                                                       #
# --------------------------------------------------------------------------- #
def test_expand_symbolic():
    out = ne.execute_expand("(a+b)*(c+d)")
    assert out == "$a c + a d + b c + b d$"


# --------------------------------------------------------------------------- #
# Обработка файла целиком                                                      #
# --------------------------------------------------------------------------- #
def test_process_text_replaces_markers():
    text = "x [NUMERIC: det, A=[[2,0],[1,3]]] y"
    new, ok, err = ne.process_text(text)
    assert ok == 1 and err == 0
    assert "[NUMERIC:" not in new
    assert "= 6$" in new


def test_process_text_error_keeps_marker_and_comments():
    text = "[NUMERIC: det, A=[[1,2,3]]]"
    new, ok, err = ne.process_text(text)
    assert err == 1
    assert "[NUMERIC:" in new
    assert "<!-- ERROR:" in new


def test_process_file_simple_fixture(tmp_path):
    src = FIXTURES / "sample_draft_simple.md"
    out = tmp_path / "chapter.md"
    errors = ne.process_file(src, out)
    assert errors == 0
    content = out.read_text(encoding="utf-8")
    assert "[NUMERIC:" not in content
    assert "\\det" in content
    assert "BA =" in content


def _normalize_ws(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.strip().splitlines())


def test_output_matches_expected_fixture(tmp_path):
    """Регрессия против золотого стандарта expected_chapter_simple.md."""
    src = FIXTURES / "sample_draft_simple.md"
    expected = (FIXTURES / "expected_chapter_simple.md").read_text(
        encoding="utf-8"
    )
    out = tmp_path / "chapter.md"
    ne.process_file(src, out)
    assert _normalize_ws(out.read_text(encoding="utf-8")) == \
        _normalize_ws(expected)
