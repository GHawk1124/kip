"""Calc cells are held to the grammar the renderer can show faithfully.

The renderer prints each assignment from its own syntax, so a construct it
cannot display would state mathematics the code did not perform. Those are
refused with a hint instead of rendered.
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
    ("y = x if x > 1 else -x", "conditional expressions"),
    ("a, b = 3.0, 4.0", "single name"),
    ("x = 1\nm = C.value('x', mm)", "method call"),
    ("x = 1\nx += 2", "augmented assignment"),
    ("a = b = 2.0", "chained assignment"),
    ("for i in range(3):\n    y = i", "loops"),
    ("def f(x):\n    return x", "definitions"),
    ("with open('f') as fh:\n    y = 1", "With statements"),
    ("s = sum([1.0, 2.0])", "List is not arithmetic"),
    ("y = x[0]", "indexing"),
    ("y = x // 2", "FloorDiv"),
    ("x = 1\nx = 2", "assigned again"),
    ("x = x + 1", "assigned again"),
    ("s = 'text'", "str values"),
])
def test_constructs_the_renderer_cannot_show_are_rejected(body, fragment):
    found = errors(body)
    assert found, f"expected an error for: {body}"
    assert any(fragment in d.message for d in found), [d.message for d in found]


@pytest.mark.parametrize("body", [
    "sigma = M * c / I",
    "r = sqrt(I / A)",
    "A = pi * d**2 / 4",
    "s = sigma.to(MPa)",
    "s = (M * c / I).to(MPa)",
    "rho = C.rho_w",
    "if x > y and x > 0:\n    z = x - y\nelse:\n    z = y - x",
    "F = 2500 * sin(theta) + 2500 * cos(theta)",
])
def test_valid_engineering_calcs_pass(body):
    assert errors(body) == []


def test_a_module_function_that_is_not_a_calculation_fails_at_run_time():
    from kip.doc import build
    doc = build(source="import math\n# %% calc b\nx = 4.0\n# %% calc c\nm = math.sqrt(x)\n",
                path="doc.py", strict=False)
    assert "math.sqrt(...) did not return an @calculation result" in doc.results["c"].error


def test_an_external_calculation_call_is_not_held_to_the_grammar():
    assert errors("sizing = analysis.size(C)") == []
    assert errors("analysis.size(C)") == []


def test_symbolic_blocks_are_not_linted():
    """Symbolic blocks are ordinary Python rendered through TypstPrinter."""
    assert errors("expr = sp.Symbol('x').diff()", kind="symbolic") == []


def test_diagnostic_line_numbers_are_absolute():
    src = "from kip import *\n\n\n\n# %% kip.calc id=b\nx = 1\ny = x if x else 0\n"
    found = [d for d in validate_all(parse(src, "doc.py"), "doc.py")
             if d.severity == "error"]
    assert found[0].line == 7


def test_syntax_error_is_reported_as_a_diagnostic():
    found = errors("x = = 1")
    assert found and "syntax error" in found[0].message


def unit_errors(body, prelude=""):
    from kip.doc.validate import unit_diagnostics
    src = f"from kip import *\n{prelude}\n# %% calc b\n{body}\n"
    return [d.message for d in unit_diagnostics(parse(src, "doc.py"))]


@pytest.mark.parametrize("body,name", [
    ("P = 2 * kN\nb = 5 * mm\nsigma = P / (b * H)", "H"),
    ("m_1 = 3 * kg\nW = m_1 * g", "g"),
    ("V_1 = L * 2", "L"),
    ("x = L.to(mm)", "L"),
])
def test_an_undefined_unit_name_used_as_a_variable_is_an_error(body, name):
    found = unit_errors(body)
    assert any(f"{name!r} is not defined here" in m for m in found), found


@pytest.mark.parametrize("body,prelude", [
    ("a = 9.81 * m / s**2", ""),
    ("rho = 7850 * kg / m**3", ""),
    ("E = 200 * GPa\nx = E.to(MPa)", ""),
    ("y = 3 * mm\nz = y.to(m)", ""),
    ("H = 40 * mm\nA_c = H * 2", ""),
    ("q = f(2)", "def f(L):\n    return L * 2"),
    ("t = Q(1.5, s)", ""),
    ("F_i = [p * N for p in loads]", ""),
])
def test_unit_names_in_unit_positions_or_defined_are_fine(body, prelude):
    assert unit_errors(body, prelude) == []


def test_calculation_functions_are_checked_too(tmp_path):
    import importlib.util
    from kip.doc.validate import ValidationError
    path = tmp_path / "loose.py"
    path.write_text("from kip import *\n\n\n@calculation\ndef weight(m_1):\n"
                    "    # equations\n    W = m_1 * g\n")
    spec = importlib.util.spec_from_file_location("loose", path)
    with pytest.raises(ValidationError) as exc:
        spec.loader.exec_module(importlib.util.module_from_spec(spec))
    assert exc.value.diagnostics[0].line == 7
    assert "'g' is not defined here" in exc.value.diagnostics[0].message
