"""End-to-end: source in, correct vector PDF out."""
import hashlib
from pathlib import Path

import pymupdf
import pytest

from kip.doc import build
from kip.doc.kernel import ExecutionError
from kip.render import emit, render
from kip.render.layout import Layout, PageSpec, auto_layout
from kip.render.pdf import block_geometry, compile_pdf, measure_heights
from kip.units import ureg

EXAMPLE = Path(__file__).parent / "fixtures" / "bracket" / "doc.py"

DOC = '''from kip import *

# %% kip.text id=intro
"""Peak stress is @val:sigma_max, see @blk:calc1."""

# %% kip.calc id=calc1 result_unit=MPa
sigma_max = M * c / I

# %% kip.given id=inputs
M = 0.75 * kN * m
c = 20 * mm
I = 133333.333 * mm**4
'''


def test_builds_and_computes_correctly():
    doc = build(source=DOC, path="doc.py")
    assert not doc.errors
    assert all(r.ok for r in doc.results.values())
    sigma = doc.value("sigma_max")
    assert sigma.units == ureg.MPa
    assert sigma.magnitude == pytest.approx(112.5, rel=1e-3)


def test_result_unit_replaces_the_unusable_to_call():
    """`.to()` is rejected, so conversion is block metadata."""
    doc = build(source=DOC, path="doc.py")
    assert "MPa" in doc.results["calc1"].latex
    assert "8.993" not in doc.results["calc1"].latex


def test_result_unit_accepts_a_per_name_mapping():
    src = '''from kip import *

# %% kip.calc id=sec result_unit="I_xx=mm**4, c_out=mm"
I_xx = b * h**3 / 12
c_out = h / 2

# %% kip.given id=g
b = 25 * mm
h = 40 * mm
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
    assert "112.500 MPa" in text
    assert "@val:" not in text


def test_dimensionless_values_have_no_trailing_unit():
    src = '''from kip import *

# %% kip.text id=t
"""Margin @val:MS."""

# %% kip.calc id=c
MS = a / b - 1

# %% kip.given id=g
a = 184 * MPa
b = 112.5 * MPa
'''
    doc = build(source=src, path="doc.py")
    assert "Margin 0.636." in doc.results["t"].text


def test_failed_block_does_not_abort_non_strict_build():
    src = DOC.replace("I = 133333.333 * mm**4", "I = 0 * mm**4")
    doc = build(source=src, path="doc.py", strict=False)
    assert any(r.failed for r in doc.results.values())


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


def test_dangling_block_reference_warns_but_still_compiles():
    """A typo in prose must not fail the whole build.

    Typst raises a hard 'label does not exist' error for a dangling link, so
    unknown @blk: targets degrade to plain text and are reported by kip check.
    """
    src = '''from kip import *

# %% kip.text id=t
"""See @blk:nonexistent and @val:missing."""

# %% kip.given id=g
x = 1 * mm
'''
    doc = build(source=src, path="doc.py", strict=False)
    pdf = compile_pdf(emit(doc, Layout()))
    assert len(pdf) > 0
    messages = [d.message for d in doc.warnings]
    assert any("no such block" in m for m in messages)
    assert any("no defined value" in m for m in messages)


def test_scaffolded_project_builds(tmp_path):
    """`kip new` must produce a document that `kip build` accepts."""
    from typer.testing import CliRunner

    from kip.cli import app

    runner = CliRunner()
    target = tmp_path / "proj"
    assert runner.invoke(app, ["new", str(target), "--no-sync"]).exit_code == 0
    assert (target / "doc.py").exists()
    assert (target / "layout.toml").exists()

    doc = build(path=target / "doc.py")
    assert not doc.errors
    assert not doc.warnings, [d.message for d in doc.warnings]
    out = render(doc, "out.pdf", layout=Layout())
    assert out.stat().st_size > 0
