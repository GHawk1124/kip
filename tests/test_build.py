"""End-to-end: source in, correct vector PDF out."""
import hashlib
from pathlib import Path

import pymupdf
import pytest

from kip.doc import build
from kip.doc.kernel import ExecutionError
from kip.doc.validate import ValidationError
from kip.render import emit, render
from kip.render.layout import Layout, PageSpec, auto_layout
from kip.render.pdf import block_geometry, compile_pdf, measure_heights
from kip.units import ureg

EXAMPLE = Path(__file__).parent / "fixtures" / "bracket" / "doc.py"

DOC = '''from kip import *

# %% kip.text id=intro
"""Peak stress is @val:sigma_max, see @blk:calc1."""

# %% kip.given id=inputs
M = 0.75 * kN * m
c = 20 * mm
I = 133333.333 * mm**4

# %% kip.calc id=calc1 result_unit=MPa
sigma_max = M * c / I
'''


def test_builds_and_computes_correctly():
    doc = build(source=DOC, path="doc.py")
    assert not doc.errors
    assert all(r.ok for r in doc.results.values())
    sigma = doc.value("sigma_max")
    assert sigma.units == ureg.MPa
    assert sigma.magnitude == pytest.approx(112.5, rel=1e-3)


def shown(result) -> str:
    return "\n".join(eq.wide() for eq in result.equations)


def test_result_unit_sets_the_displayed_unit():
    doc = build(source=DOC, path="doc.py")
    assert '112.5 thin "MPa"' in shown(doc.results["calc1"])


def test_to_inside_an_equation_converts_without_rendering_the_call():
    doc = build(source="""from kip import *
# %% calc s "Stress"
M = 0.75 * kN * m
W = 6666.667 * mm**3
sigma = (M / W).to(MPa)
""", path="doc.py")
    text = shown(doc.results["s"])
    assert "to" not in text.replace("thin", "")
    assert 'frac(M, W)' in text and '112.5 thin "MPa"' in text


def test_result_unit_accepts_a_per_name_mapping():
    src = '''from kip import *

# %% kip.given id=g
b = 25 * mm
h = 40 * mm

# %% kip.calc id=sec result_unit="I_xx=mm**4, c_out=mm"
I_xx = b * h**3 / 12
c_out = h / 2
'''
    doc = build(source=src, path="doc.py")
    assert doc.value("I_xx").units == ureg.mm ** 4
    assert doc.value("c_out").units == ureg.mm


def test_result_unit_mismatch_is_a_clear_error():
    src = DOC.replace("result_unit=MPa", "result_unit=kg")
    with pytest.raises(ExecutionError) as exc:
        build(source=src, path="doc.py")
    assert "cannot convert" in str(exc.value)


def test_val_citation_resolves_to_a_live_value():
    doc = build(source=DOC, path="doc.py")
    text = doc.results["intro"].text
    assert "112.5 MPa" in text
    assert "@val:" not in text


def test_dimensionless_values_have_no_trailing_unit():
    src = '''from kip import *

# %% kip.text id=t
"""Margin @val:MS."""

# %% kip.given id=g
a = 184 * MPa
b = 112.5 * MPa

# %% kip.calc id=c
MS = a / b - 1
'''
    doc = build(source=src, path="doc.py")
    pdf = pymupdf.open(stream=compile_pdf(emit(doc)), filetype="pdf")
    assert "Margin 0.6356." in "".join(page.get_text() for page in pdf)


def test_ratios_of_mixed_units_are_reduced_to_plain_numbers():
    """100 MPa / 10 ksi is 1.45, not "10 MPa/ksi"; angles and percent keep their units."""
    doc = build(source='''from kip import *

# %% text t
"""Ratio @val:r, deflection ratio @val:k, angle @val:theta, share @val:p."""

# %% inputs g
a = 100 * MPa
b = 10 * ksi
d = 1.19 * mm
E = 68.9 * GPa
w = 2.5 * kN / m

# %% calc c
r = a / b
k = w * (1.8 * m)**4 / (E * (100 * mm)**4 * d)
theta = 30 * deg
p = 5 * percent
''', path="doc.py")
    text = shown(doc.results["c"])
    assert "= 1.45\n" in text + "\n" and "ksi" not in text.split("=")[-1]
    assert "GPa" not in text.splitlines()[1].split("=")[-1]  # k is a plain number
    assert doc.results["t"].text.count("#text(") == 4
    for expected in ('"1.45"', '"30°"', '"5 %"'):
        assert expected in doc.results["t"].text


def test_a_name_computed_by_one_cell_cannot_be_bound_again_by_another():
    """Otherwise later tables and prose show a value different from the one printed."""
    src = '''from kip import *
limit = 2

# %% inputs g
F_ty = 240 * MPa

# %% calc stress
sigma_allow = F_ty / 1.5       # -> MPa

# %% plot p
x = [0, 1]
plot(x, x)

# %% table t
x = [1, 2]
Table(["x"], [(v,) for v in x])

# %% calc deflection
sigma_allow = F_ty / 2         # -> MPa

# %% calc again
limit = 3
'''
    doc = build(source=src, path="doc.py", strict=False)
    errors = {d.message: d for d in doc.errors}
    assert set(errors) == {"'sigma_allow' is already defined in cell 'stress' (line 8)",
                           "'limit' is already defined in the prelude (line 2)"}
    assert errors["'sigma_allow' is already defined in cell 'stress' (line 8)"].line == 19
    assert errors["'sigma_allow' is already defined in cell 'stress' (line 8)"].block_id == "deflection"
    with pytest.raises(ValidationError):
        build(source=src, path="doc.py")


def test_failed_block_does_not_abort_non_strict_build():
    src = DOC.replace("I = 133333.333 * mm**4", "I = 0 * mm**4")
    doc = build(source=src, path="doc.py", strict=False)
    assert any(r.failed for r in doc.results.values())


def test_a_failure_blocks_its_dependents_instead_of_cascading():
    doc = build(source='''from kip import *
# %% given a
x = 1 * mm
# %% calc b
y = x / (x - x)
# %% calc c
z = y * 2
# %% text d
"""z is @val:z"""
''', path="doc.py", strict=False)
    assert doc.results["b"].failed
    assert doc.results["c"].state == "BLOCKED" and not doc.results["c"].failed
    assert doc.results["c"].reason == "Waiting on b, which failed."


def test_a_calculation_reading_a_later_value_is_reported_before_running():
    from kip.doc.validate import ValidationError
    with pytest.raises(ValidationError) as exc:
        build(source='''from kip import *
# %% calc b
y = x * 2
# %% given a
x = 1 * mm
''', path="doc.py")
    assert "'x' is used before it is defined; cell 'a'" in str(exc.value)


def test_a_failure_names_the_line_in_the_authors_module(tmp_path):
    from kip.doc.kernel import where
    (tmp_path / "analysis.py").write_text('''from kip import *


@calculation
def moment(P, L):
    # equations
    M = P * L
    Z = M / (L - L)
''')
    doc = build(source='''from kip import *
import analysis
# %% calc bending "Bending"
analysis.moment(2 * kN, 100 * mm)
''', path=tmp_path / "doc.py", strict=False)
    assert where(doc.results["bending"]) == f"{tmp_path / 'analysis.py'}:8"


# --- rendering --------------------------------------------------------------

def test_pdf_is_fully_vector(tmp_path):
    doc = build(path=EXAMPLE)
    doc.path = tmp_path / "doc.py"
    out = render(doc, "out.pdf", layout=Layout())
    pdf = pymupdf.open(out)
    images = sum(len(pdf[i].get_images()) for i in range(pdf.page_count))
    text = sum(len(pdf[i].get_text()) for i in range(pdf.page_count))
    assert images == 0, "equations must be vector text, not rasters"
    assert text > 500, "equations must be extractable text"


def test_math_font_is_embedded(tmp_path):
    doc = build(path=EXAMPLE)
    doc.path = tmp_path / "doc.py"
    out = render(doc, "out.pdf", layout=Layout())
    pdf = pymupdf.open(out)
    fonts = {f[3] for i in range(pdf.page_count) for f in pdf[i].get_fonts()}
    assert any("Math" in f for f in fonts), fonts


def test_build_is_byte_reproducible():
    """Same input must give identical PDF bytes, run to run."""
    hashes = set()
    for _ in range(3):
        doc = build(path=EXAMPLE)
        hashes.add(hashlib.sha256(compile_pdf(emit(doc, Layout()))).hexdigest())
    assert len(hashes) == 1


def test_symbolic_block_order_is_stable():
    """block.defs is a frozenset; rendering must use source order."""
    src = '''from kip import *
import sympy as sp

# %% kip.symbolic id=s
a_expr = sp.Symbol("x") * 2
b_expr = sp.Symbol("y") * 3
c_expr = sp.Symbol("z") * 4
'''
    outputs = {build(source=src, path="doc.py").results["s"].typst for _ in range(5)}
    assert len(outputs) == 1
    out = outputs.pop()
    assert out.index('a_"expr"') < out.index('b_"expr"') < out.index('c_"expr"')


def test_block_geometry_is_recoverable():
    """Rendered block positions remain queryable."""
    doc = build(path=EXAMPLE)
    geoms = {g.id: g for g in block_geometry(emit(doc, Layout()))}
    for block in doc.ordered_blocks():
        assert block.id in geoms
        assert geoms[block.id].page >= 1


def test_auto_layout_produces_no_overlaps():
    doc = build(path=EXAMPLE)
    lay = Layout(page=PageSpec(columns=2))
    heights = measure_heights(doc, lay.page.column_width())
    auto_layout(doc, lay, heights=heights, columns=2)

    by_col: dict[tuple[int, float], list[tuple[float, float]]] = {}
    for bid, pos in lay.blocks.items():
        by_col.setdefault((pos.page, pos.x), []).append((pos.y, heights.get(bid, 0)))
    for spans in by_col.values():
        spans.sort()
        for (y1, h1), (y2, _) in zip(spans, spans[1:]):
            assert y1 + h1 <= y2 + 1e-6, "blocks overlap in a column"


def test_layout_toml_round_trips(tmp_path):
    lay = Layout(page=PageSpec(title="T", columns=2))
    doc = build(path=EXAMPLE)
    auto_layout(doc, lay, columns=2)
    p = lay.save(tmp_path / "layout.toml")

    back = Layout.load(p)
    assert back.page.title == "T"
    assert back.page.columns == 2
    assert set(back.blocks) == set(lay.blocks)
    for bid in lay.blocks:
        assert back.blocks[bid].x == pytest.approx(lay.blocks[bid].x)
        assert back.blocks[bid].y == pytest.approx(lay.blocks[bid].y)


def test_pinned_blocks_survive_auto_layout():
    from kip.render.layout import Position

    doc = build(path=EXAMPLE)
    lay = Layout(page=PageSpec(columns=2))
    lay.blocks["intro"] = Position(x=99.0, y=88.0, w=50.0, page=1, pinned=True)
    auto_layout(doc, lay, columns=2)
    assert lay.blocks["intro"].x == 99.0 and lay.blocks["intro"].y == 88.0


def test_dangling_references_are_errors_but_a_draft_still_compiles():
    """A typo in a reference is an error, not plain text shipped in the PDF.

    Typst raises a hard 'label does not exist' error for a dangling link, so
    unknown @blk: targets still degrade to plain text when a draft is
    rendered without strict checking.
    """
    src = '''from kip import *

# %% kip.text id=t
"""See @blk:nonexistent and @val:missing.
Also @val:xx and @blk:g."""

# %% kip.given id=g
x = 1 * mm
'''
    doc = build(source=src, path="doc.py", strict=False)
    pdf = compile_pdf(emit(doc, Layout()))
    assert len(pdf) > 0
    found = {d.message: d for d in doc.errors}
    assert found["@blk:nonexistent refers to no such block"].line == 4
    assert found["@val:missing refers to no defined value"].line == 4
    assert found["@val:xx refers to no defined value"].hint == "did you mean @val:x?"
    assert found["@val:xx refers to no defined value"].line == 5
    assert len(found) == 3
    with pytest.raises(ValidationError):
        build(source=src, path="doc.py")


def test_citations_of_unknown_sources_and_requirements_are_errors(tmp_path):
    src = '''from kip import *

# %% text "Notes"
"""Per @src:roark and @src:rorak; meets @req:REQ-001 and @req:REQ-009."""

# %% sources refs
Sources(roark=Source(title="Formulas for Stress and Strain"))

# %% requirements reqs
Requirements.load()
'''
    (tmp_path / "input").mkdir()
    from kip.sheets import save_workbook
    from openpyxl import Workbook
    book = Workbook()
    book.active.title = "Item"
    book["Item"].append(["id", "name"])
    book["Item"].append(["bracket", "Bracket"])
    book.create_sheet("Inputs").append(["id", "text", "verification"])
    book["Inputs"].append(["REQ-001", "Carry the load.", "analysis"])
    save_workbook(book, tmp_path / "input" / "requirements.xlsx")
    (tmp_path / "doc.py").write_text(src, encoding="utf-8")
    doc = build(tmp_path / "doc.py", strict=False)
    found = {d.message: d for d in doc.errors}
    assert set(found) == {"@src:rorak refers to no reference in this document's sources",
                          "@req:REQ-009 refers to no loaded requirement"}
    assert found["@src:rorak refers to no reference in this document's sources"].hint == \
        "did you mean @src:roark?"


def test_scaffolded_project_builds(tmp_path):
    """`kip new` must produce a document that `kip build` accepts."""
    from typer.testing import CliRunner

    from kip.cli import app

    runner = CliRunner()
    target = tmp_path / "proj"
    assert runner.invoke(app, ["new", str(target), "--no-sync"]).exit_code == 0
    assert (target / "doc.py").exists()
    assert (target / "input" / "references.xlsx").exists()
    assert 'run_document(__file__, title="Proj")' in (target / "doc.py").read_text()

    doc = build(path=target / "doc.py")
    assert not doc.errors
    assert not doc.warnings, [d.message for d in doc.warnings]
    out = render(doc, "out.pdf", layout=Layout())
    assert out.stat().st_size > 0


def test_units_render_as_their_symbols():
    """psi's long name is pound_force_per_square_inch; only the symbol is shown."""
    doc = build(source='''from kip import *
# %% calc loaded "Loaded"
dp_clean = 0.4842499437890715 * psi
dp_cake = 0.4115 * psi
dp_total = dp_clean + dp_cake
''')
    text = shown(doc.results["loaded"])
    assert "pound" not in text
    # an input reads as written; the substituted value is rounded
    assert '0.4842499437890715 thin "psi"' in text
    assert '0.4842 thin "psi" + 0.4115 thin "psi"' in text


def test_a_bare_unit_name_in_an_equation_is_a_unit():
    doc = build(source='''from kip import *
# %% calc bearing "Bearing"
F = 250.0 * lbf
A_b = 2.0 * inch**2
p_brg = F / A_b
q = 3 * p_brg / psi
''')
    text = shown(doc.results["bearing"])
    assert '"lbf"' in text and '"in²"' in text
    assert 'frac(3 dot p_"brg", "psi")' in text


def test_sqrt_keeps_units():
    doc = build(source='''from kip import *
# %% calc r "Radius"
A_c = 400 * mm**2
r = sqrt(A_c / pi)
''')
    assert doc.value("r").units == ureg.mm
    assert "sqrt(frac(A_c, pi))" in shown(doc.results["r"])


def test_if_statements_show_the_condition_and_taken_branch():
    doc = build(source='''from kip import *
# %% calc g "Governing"
s_1 = 20 * MPa
s_2 = 30 * MPa
if s_1 > s_2:
    s_gov = s_1
else:
    s_gov = s_2
''')
    text = shown(doc.results["g"])
    assert '"false"' in text and '"else"' in text
    assert 's_"gov" = s_2 = 30 thin "MPa"' in text


def test_calculation_validation_errors_name_the_line_in_the_authors_file(tmp_path):
    import importlib.util
    from kip.doc.validate import ValidationError
    path = tmp_path / "bad_analysis.py"
    path.write_text('''from kip import *


@calculation
def moment(P, L):
    # equations
    M = P * L
    Z = M if P else L
''')
    spec = importlib.util.spec_from_file_location("bad_analysis", path)
    with pytest.raises(ValidationError) as exc:
        spec.loader.exec_module(importlib.util.module_from_spec(spec))
    assert exc.value.diagnostics[0].line == 8


def test_two_documents_import_their_own_analysis_modules(tmp_path):
    for name, factor in (("one", 2), ("two", 3)):
        folder = tmp_path / name
        folder.mkdir()
        (folder / "analysis.py").write_text(f"FACTOR = {factor}\n")
        (folder / "doc.py").write_text(
            "import analysis\n# %% calc c\ny = analysis.FACTOR * 1.0\n")
    import sys
    assert build(path=tmp_path / "one" / "doc.py").value("y") == 2
    assert build(path=tmp_path / "two" / "doc.py").value("y") == 3
    assert "analysis" not in sys.modules


def test_a_converted_result_is_converted_for_the_next_line_too():
    doc = build(source='''from kip import *
# %% inputs i
P = 150 * N
L = 400 * mm
E = 68.9 * GPa
I_x = 39062.5 * mm**4
d_allow = 2 * mm
# %% calc d "Deflection"
d_tip = P * L**3 / (3 * E * I_x)   # -> mm
n = d_allow / d_tip
''', path="doc.py")
    n = doc.value("n")
    assert n.dimensionless and str(n.units) == "dimensionless"
    assert shown(doc.results["d"]).endswith("= 1.682")


def test_calculation_functions_convert_before_the_next_equation(tmp_path):
    (tmp_path / "beam.py").write_text('''from kip import *


@calculation
def deflection(P, L, E, I_x, d_allow):
    # equations
    d_tip = P * L**3 / (3 * E * I_x)   # -> mm
    n = d_allow / d_tip
    return locals()
''')
    doc = build(source='''from kip import *
import beam
# %% calc c
r = beam.deflection(150 * N, 400 * mm, 68.9 * GPa, 39062.5 * mm**4, 2 * mm)
''', path=tmp_path / "doc.py")
    assert str(doc.value("r").n.units) == "dimensionless"
