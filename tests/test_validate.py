"""The constructs handcalcs renders silently wrong must be rejected.

These valid Python constructs cause handcalcs to produce
into *false mathematics* without raising.  A document that states false maths
and looks plausible is the worst possible failure mode, so these are errors.
"""
import pytest

from kip.doc.loader import parse
from kip.doc.validate import validate_all


def diags(body, kind="calc"):
    src = f"from kip import *\n\n# %% kip.{kind} id=b\n{body}\n"
    return validate_all(parse(src, "doc.py"), "doc.py")


def errors(body, kind="calc"):
    return [d for d in diags(body, kind) if d.severity == "error"]


@pytest.mark.parametrize("body,fragment", [
    ("y = x if x > 1 else -x", "condition is silently dropped"),
    ("a, b = 3.0, 4.0", "renders INCORRECTLY"),
    ("s = sigma.to(MPa)", "attribute access"),
    ("s = (M * c / I).to(MPa)", "attribute access"),
    ("m = math.sqrt(x)", "attribute access"),
    ("x = 1\nx += 2", "augmented assignment"),
    ("a = b = 2.0", "chained assignment"),
    ("for i in range(3):\n    y = i", "loops"),
    ("def f(x):\n    return x", "function definitions"),
    ("with open('f') as fh:\n    y = 1", "with statements"),
])
def test_silently_wrong_constructs_are_rejected(body, fragment):
    found = errors(body)
    assert found, f"expected an error for: {body}"
    assert any(fragment in d.message for d in found), [d.message for d in found]


@pytest.mark.parametrize("body", [
    "sigma = M * c / I",
    "r = sqrt(I / A)",
    "A = pi * d**2 / 4",
    "s = sum([1.0, 2.0])",
    "if x > y:\n    z = x - y\nelse:\n    z = y - x",
    "F = 2500 * sin(theta) + 2500 * cos(theta)",
])
def test_valid_engineering_calcs_pass(body):
    assert errors(body) == []


def test_trailing_underscore_is_a_warning_not_an_error():
    d = diags("x_ = 1.0")
    assert [x.severity for x in d] == ["warning"]
    assert "empty subscript" in d[0].message


def test_symbolic_blocks_are_not_linted():
    """Symbolic blocks go through TypstPrinter, not handcalcs."""
    assert errors("expr = sp.Symbol('x').diff()", kind="symbolic") == []


def test_diagnostic_line_numbers_are_absolute():
    src = "from kip import *\n\n\n\n# %% kip.calc id=b\nx = 1\ny = x if x else 0\n"
    found = [d for d in validate_all(parse(src, "doc.py"), "doc.py")
             if d.severity == "error"]
    assert found[0].line == 7


def test_syntax_error_is_reported_as_a_diagnostic():
    found = errors("x = = 1")
    assert found and "syntax error" in found[0].message
