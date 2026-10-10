"""``assert`` in a calculation is a shown check: it never stops the document."""
import inspect
import re
import unicodedata

import pymupdf
import pytest
from typer.testing import CliRunner

from kip import MPa, calculation, mm
from kip.cli import app
from kip.doc import build
from kip.doc.kernel import ExecutionError
from kip.doc.validate import ValidationError
from kip.render import emit
from kip.render.pdf import compile_pdf

DOC = '''from kip import *

# %% inputs g
sigma = 120 * MPa
sigma_allow = 100 * MPa

# %% calc margin "Margin"
MS = sigma_allow / sigma - 1
assert MS >= 0, "Bending margin"
assert sigma <= 2 * sigma_allow
U = sigma / sigma_allow

# %% text t
"""Utilisation @val:U."""
'''


def text(doc):
    pdf = pymupdf.open(stream=compile_pdf(emit(doc)), filetype="pdf")
    return " ".join(unicodedata.normalize("NFKC", "".join(page.get_text() for page in pdf)).split())


def test_a_failed_check_is_shown_and_the_rest_of_the_document_still_runs():
    doc = build(source=DOC, path="doc.py")  # strict: a failed check is not an error
    result = doc.results["margin"]
    assert [(c.line, c.passed) for c in result.assertions] == [(9, False), (10, True)]
    failed = result.assertions[0]
    assert failed.describe() == ("Bending margin: MS >= 0 is false "
                                 "(MS = -0.1667)")
    assert doc.value("U").magnitude == pytest.approx(1.2)  # the line after still ran
    shown = text(doc)
    assert "Bending margin" in shown and "NOT OK" in shown
    assert re.search(r"check σ ?≤ ?2 ⋅ ?σ ?allow ⇒ 120 MPa ?≤ ?2 ⋅ ?100 MPa ⇒ OK", shown)
    assert "Utilisation 1.2." in shown
    # Checks take no equation number: MS is (1), U is (2).
    assert "(1)" in shown and "(2)" in shown and "(3)" not in shown


def test_kip_check_fails_on_a_failed_check_and_kip_build_still_writes_the_pdf(tmp_path):
    path = tmp_path / "doc.py"
    path.write_text(DOC, encoding="utf-8")
    runner = CliRunner()
    checked = runner.invoke(app, ["check", str(path)])
    assert checked.exit_code == 1
    assert f"{path}:9: error: [margin] check failed: Bending margin: MS >= 0 is false" in checked.output
    built = runner.invoke(app, ["build", str(path)])
    assert built.exit_code == 0 and f"{path}:9: warning: [margin] check failed" in built.output
    assert (tmp_path / "output").exists()
    path.write_text(DOC.replace("120 * MPa", "80 * MPa"), encoding="utf-8")
    passed = runner.invoke(app, ["check", str(path)])
    assert passed.exit_code == 0 and "checks 2 passed" in passed.output


def test_only_checks_in_the_branch_taken_are_evaluated():
    doc = build(source='''from kip import *
# %% inputs g
t = 3 * mm
# %% calc c
if t > 2 * mm:
    k = 1
    assert t < 5 * mm
else:
    k = 2
    assert t < 1 * mm
''', path="doc.py")
    assert [(c.condition, c.passed) for c in doc.results["c"].assertions] == [("t < 5 * mm", True)]


@calculation
def plate(t):
    allowable = 100 * MPa
    assert t > 0 * mm  # setup: an ordinary assertion
    # equations
    stress = 1000 * MPa * mm / t       # -> MPa
    assert stress <= allowable, "Plate stress"


def test_checks_in_an_external_calculation_report_their_own_file_and_line():
    result = plate(5 * mm)
    first = inspect.getsourcelines(plate.__wrapped__)[1]
    doc_source = '''from kip import *
import test_checks
# %% calc p
test_checks.plate(5 * mm)
'''
    import sys
    sys.modules.setdefault("test_checks", sys.modules[__name__])
    doc = build(source=doc_source, path="doc.py")
    check, = doc.results["p"].assertions
    assert not check.passed and check.message == "Plate stress"
    assert check.file.endswith("test_checks.py") and check.line == first + 6
    assert result.stress.magnitude == pytest.approx(200)
    with pytest.raises(AssertionError):
        plate(-1 * mm)  # setup asserts still raise


@pytest.mark.parametrize("cell,message", [
    ("# %% inputs g\nx = 1 * mm\nassert x > 0 * mm", "a check (assert) is not shown in this cell"),
    ("# %% calc c\nx = 1 * mm\nassert x > 0 * mm, x", "a check's message must be a plain string"),
])
def test_checks_are_refused_where_they_cannot_be_shown(cell, message):
    with pytest.raises(ValidationError) as caught:
        build(source="from kip import *\n" + cell, path="doc.py")
    assert any(message in d.message and d.line == 4 for d in caught.value.diagnostics)


def test_a_check_that_cannot_be_evaluated_fails_its_cell_with_the_line():
    with pytest.raises(ExecutionError, match=re.escape(
            "doc.py:4: [c] cannot evaluate the check: cannot compare x (a length) "
            "with 5 * MPa (a pressure or stress)")):
        build(source='''from kip import *
# %% calc c
x = 1 * mm
assert x <= 5 * MPa
''', path="doc.py")
