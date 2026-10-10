"""What an author -- usually an agent -- is told after each edit, and how values read."""
import json
import subprocess
import sys
import unicodedata

import pymupdf
import pytest
from typer.testing import CliRunner

from kip import kN, linspace, m, mm
from kip.cli import app
from kip.doc import build
from kip.doc.kernel import where
from kip.render import emit
from kip.render.pdf import compile_pdf

BEAM = '''from kip import *

# %% inputs g "Loads"
w = 2.5 * kN / m
L = 1.8 * m
b = 50 * mm
h = 100 * mm

# %% calc stress "Bending stress"
M = w * L**2 / 8              # -> kN*m
S = b * h**2 / 6              # -> mm**3
sigma = M / S                 # -> MPa
MS = 160 * MPa / sigma - 1
'''


def check(tmp_path, source, *args):
    path = tmp_path / "doc.py"
    path.write_text(source, encoding="utf-8")
    return CliRunner().invoke(app, ["check", str(path), *args]), path


# -- uv run doc.py -------------------------------------------------------------

def test_running_doc_py_reports_like_kip_build(tmp_path):
    path = tmp_path / "doc.py"
    path.write_text('from kip import *\nreport = run_document(__file__)\n' + BEAM.replace(
        "from kip import *\n", "").replace("MS = 160", "assert sigma < 1 * MPa\nMS = 160"),
        encoding="utf-8")
    run = subprocess.run([sys.executable, "doc.py"], cwd=tmp_path, capture_output=True,
                         text=True, encoding="utf-8")
    assert run.returncode == 0, run.stderr
    assert "doc.py:14: warning: [stress] check failed: sigma < 1 * MPa is false" in run.stderr
    assert "built" in run.stdout
    path.write_text(path.read_text().replace("sigma = M / S", "sigma = M / S + 1"))
    run = subprocess.run([sys.executable, "doc.py"], cwd=tmp_path, capture_output=True,
                         text=True, encoding="utf-8")
    assert run.returncode == 1
    assert "doc.py:13: error: [stress] cannot add M / S (a pressure or stress) and 1 (a plain number)" \
        in run.stderr
    assert "Traceback" not in run.stderr


# -- where a failure is --------------------------------------------------------

@pytest.mark.parametrize("edit,line,message", [
    (("MS = 160 * MPa / sigma - 1", "MS = 160 * MPa / (sigma - sigma)"), 13,
     "ZeroDivisionError"),
    (("S = b * h**2 / 6              # -> mm**3", "S = b * h**2 / 6 + t   # -> mm**3"), 11,
     "NameError: name 't' is not defined"),
    (("sigma = M / S                 # -> MPa", "sigma = M / b                 # -> MPa"), 12,
     "cannot convert 'sigma' from kN·m/mm to MPa: sigma is a force, but MPa is a pressure or stress"),
    (("MS = 160 * MPa / sigma - 1", "MS = 160 * MPa - 1"), 13,
     "cannot subtract 1 (a plain number) from 160 * MPa (a pressure or stress)"),
])
def test_a_failure_while_a_cell_runs_names_its_line_and_what_is_wrong(edit, line, message):
    doc = build(source=BEAM.replace(*edit), path="doc.py", strict=False)
    result = doc.results["stress"]
    assert where(result) == f"doc.py:{line}"
    assert message in result.error


def test_a_unit_mistake_inside_an_at_calculation_says_what_is_wrong(tmp_path):
    (tmp_path / "beam_calc.py").write_text('''from kip import *


@calculation
def stress(w, L, b, h):
    # equations
    M = w * L**2 / 8
    S = b * h**2 / 6
    MS = 160 * MPa / (M / S) - 1 * MPa
''')
    doc = build(source='''from kip import *
import beam_calc
# %% calc bending "Bending"
beam_calc.stress(2.5 * kN / m, 1.8 * m, 50 * mm, 100 * mm)
''', path=tmp_path / "doc.py", strict=False)
    result = doc.results["bending"]
    assert where(result) == f"{tmp_path / 'beam_calc.py'}:9"
    assert result.error == ("cannot subtract 1 * MPa (a pressure or stress) "
                            "from 160 * MPa / (M / S) (a plain number)")


def test_an_if_test_that_mixes_units_says_so():
    doc = build(source=BEAM + "if sigma < 160:\n    ok = 1\n", path="doc.py", strict=False)
    assert where(doc.results["stress"]) == "doc.py:14"
    assert "cannot compare sigma (a pressure or stress) with 160 (a plain number)" \
        in doc.results["stress"].error


def test_a_plot_cell_error_names_its_line():
    doc = build(source=BEAM + '''
# %% plot p
x = linspace(0 * m, L, 5)
plot(x, w * x, ylable="Load")
''', path="doc.py", strict=False)
    assert where(doc.results["p"]) == "doc.py:17"


def test_one_mistake_is_reported_once(tmp_path):
    result, path = check(tmp_path, BEAM.replace("MS = 160 * MPa / sigma - 1",
                                                "MS = 160 * MPa / sigma\nMS += -1"))
    assert result.output.count("error:") == 1 and "1 error(s), 0 warning(s)" in result.output
    result, path = check(tmp_path, BEAM.replace("S = b * h**2 / 6 ", "S = b * t**2 / 6 "))
    assert result.output.count("error:") == 1 and "undefined" not in result.output
    assert f"{path}:11: error: [stress] NameError" in result.output


# -- reading results without the PDF ---------------------------------------------

def test_kip_show_lists_every_value_in_source_order(tmp_path):
    path = tmp_path / "doc.py"
    path.write_text(BEAM + "assert MS >= 0, 'Bending margin'\n", encoding="utf-8")
    shown = CliRunner().invoke(app, ["show", str(path)]).output
    lines = [line.strip() for line in shown.splitlines()]
    stress = lines.index(f'calc stress "Bending stress"  {path}:9')
    assert lines[stress + 1:stress + 6] == [
        "M = 1.013 kN·m", "S = 83333 mm³", "sigma = 0.01215 kN·m/mm³".replace(
            "0.01215 kN·m/mm³", "12.15 MPa"), "MS = 12.17", "check MS >= 0 (Bending margin): OK"]


def test_kip_check_json_has_problems_values_and_checks(tmp_path):
    result, path = check(tmp_path, BEAM + "assert MS >= 20\n", "--json")
    assert result.exit_code == 1
    data = json.loads(result.stdout)
    assert data["ok"] is False and data["errors"] == 1
    problem, = data["problems"]
    assert (problem["line"], problem["block"]) == (14, "stress")
    assert problem["message"].startswith("check failed: MS >= 20 is false")
    stress = next(b for b in data["blocks"] if b["id"] == "stress")
    assert stress["values"]["sigma"] == {"value": pytest.approx(12.15), "unit": "MPa",
                                         "text": "12.15 MPa"}
    assert stress["checks"][0]["passed"] is False
    broken, _ = check(tmp_path, BEAM.replace("# %% calc stress", "# %% calcs stress"), "--json")
    assert json.loads(broken.stdout)["problems"][0]["line"] == 9


# -- layout ------------------------------------------------------------------------

def test_a_too_wide_equation_is_set_one_step_per_row_at_full_size(tmp_path):
    terms = " + ".join(f"w * L**4 / ({n} * 70 * GPa * b * h**3)" for n in (384, 24, 30, 120))
    source = BEAM + f"k = ({terms}) / (3 * mm + 4 * mm + 5 * mm + 6 * mm)\n"
    doc = build(source=source, path="doc.py")
    assert "rows: (" in emit(doc)["main.typ"].decode()
    pdf = pymupdf.open(stream=compile_pdf(emit(doc)), filetype="pdf")
    sizes = [s["size"] for b in pdf[0].get_text("dict")["blocks"]
             for line in b.get("lines", []) for s in line["spans"] if "6 mm" in s["text"]]
    assert sizes and min(sizes) >= 9.5  # shrunk to fit one row, it was about 4 pt
    result, _ = check(tmp_path, source)
    assert result.exit_code == 0 and "warning:" not in result.output


def test_an_equation_that_still_must_shrink_is_reported(tmp_path):
    names = [f"a_{i}" for i in range(40)]
    source = ("from kip import *\n# %% inputs g\n" + "".join(f"{n} = {i} * mm\n" for i, n in enumerate(names))
              + "# %% calc c\ntotal = " + " + ".join(names) + "\n")
    result, path = check(tmp_path, source)
    assert result.exit_code == 0
    assert f"{path}:43: warning: [c] equation (1) is drawn at" in result.output
    assert "of full size to fit page 1" in result.output


def test_a_page_left_short_is_noted(tmp_path):
    source = ('from kip import *\n# %% text t\n"""#v(140mm)\n\nIntro."""\n# %% plot p\n'
              'x = linspace(0, 10, 5)\nplot(x, x, height=110)\n')
    result, _ = check(tmp_path, source)
    assert "layout: page 1 ends" in result.output and "p, " in result.output


def test_a_tall_calc_breaks_between_equations_rather_than_leave_a_gap(tmp_path):
    rows = "".join(f"x_{i} = {i + 1} * mm\n" for i in range(24))
    source = ('from kip import *\n# %% text t\n"""#v(140mm)\n\nIntro."""\n'
              '# %% calc c "Sizes" result=x_23\n' + rows)
    pdf = pymupdf.open(stream=compile_pdf(emit(build(source=source, path="doc.py"))), filetype="pdf")
    first, second = (unicodedata.normalize("NFKC", page.get_text()) for page in pdf)
    assert "SIZES" in first and "(1)" in first and "(24)" in second
    assert "x23 = 24 mm" in second.replace("\n", "")  # the result stays with the last row
    result, _ = check(tmp_path, source)
    assert "layout:" not in result.output


def test_if_rows_take_no_equation_number():
    doc = build(source=BEAM + "if MS > 0:\n    ok = 1\nelse:\n    ok = 0\nr = 2 * MS\n", path="doc.py")
    text = "".join(p.get_text() for p in pymupdf.open(stream=compile_pdf(emit(doc)), filetype="pdf"))
    assert "(5)" in text and "(6)" in text and "(7)" not in text


# -- how values read ---------------------------------------------------------------

def test_result_boxes_show_the_values_a_cell_names():
    doc = build(source=BEAM.replace('# %% calc stress "Bending stress"',
                                    '# %% calc stress "Bending stress" result=sigma,MS'), path="doc.py")
    pdf = pymupdf.open(stream=compile_pdf(emit(doc)), filetype="pdf")
    text = unicodedata.normalize("NFKC", "".join(p.get_text() for p in pdf))
    assert "σ = 12.15 MPa" in text and "MS = 12.17" in text
    hidden = build(source=BEAM.replace('"Bending stress"', '"Bending stress" result=none'), path="doc.py")
    assert "result-chip" not in emit(hidden)["main.typ"].decode()
    wrong = build(source=BEAM.replace('"Bending stress"', '"Bending stress" result=sigma_max'),
                  path="doc.py", strict=False)
    assert where(wrong.results["stress"]) == "doc.py:9"
    assert "result=sigma_max names sigma_max, which this cell does not compute" in wrong.results["stress"].error


def test_linspace_keeps_units_so_a_sweep_reads_as_its_formula():
    x = linspace(0, 1.8 * m, 5)
    assert str(x.units) == "meter" and list(x.magnitude) == pytest.approx([0, 0.45, 0.9, 1.35, 1.8])
    moment = 2.5 * kN / m * x * (1.8 * m - x) / 2
    assert moment.to("kN*m").magnitude.max() == pytest.approx(1.0125)
    assert list(linspace(1, 2, 3)) == [1, 1.5, 2]
    with pytest.raises(ValueError, match="give both ends units"):
        linspace(5, 10 * mm)
