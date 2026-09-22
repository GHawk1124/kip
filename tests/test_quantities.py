import pymupdf
import pytest

from kip import Constants, Requirements, calculation, inputs_table, nomenclature, mm, kN, MPa
from kip.doc import build
from kip.doc.kernel import execute
from kip.render import emit, render
from kip.render.pdf import compile_pdf


@calculation
def bearing(c):
    load = c.P
    diameter = c.d
    thickness = c.t
    # equations
    area = diameter * thickness
    stress = load / area  # -> MPa


@calculation
def doubled(previous):
    stress = previous.stress
    # equations
    double_stress = 2 * stress  # -> MPa


@calculation
def controlled(reqs):
    load = reqs.P
    # equations
    twice = 2 * load  # -> kN


def constants():
    return (Constants().add("P", 12 * kN, description="Design load", source="REQ-1")
            .add("d", 10 * mm, description="Pin diameter", basis="Drawing", source="DWG-1")
            .add("t", 10 * mm, description="Plate thickness", source="DWG-2")
            .add("unused", 42 * mm, description="Unrelated"))


def test_inputs_are_read_once_and_keep_sources_and_snapshot_values():
    c = constants()
    result = bearing(c)
    c.override("d", 99 * mm)
    table = inputs_table(result)
    assert [row[0].name for row in table.rows] == ["P", "d", "t"]
    assert table.rows[1][1:] == ("10 mm", "Pin diameter; Drawing", "DWG-1")
    assert table.rows[2][1:] == ("10 mm", "Plate thickness", "DWG-2")
    assert result.stress.to(MPa).magnitude == 120


def test_nomenclature_uses_alias_origins_not_equal_values():
    result = bearing(constants())
    rows = {r[0].name: r[1:] for r in nomenclature(result).rows}
    assert rows["diameter"] == ("Pin diameter", "mm")
    assert rows["thickness"] == ("Plate thickness", "mm")
    assert rows["stress"] == ("-", "MPa")
    assert "unused" not in rows and "c" not in rows
    assert nomenclature(result, overrides={"stress": "Bearing stress"}).rows[-1][1] == "Bearing stress"
    with pytest.raises(ValueError, match="unknown symbols"):
        nomenclature(result, overrides={"misspelled": "Oops"})


def test_upstream_calculation_values_are_recorded_as_inputs():
    result = doubled(bearing(constants()))
    assert [(r[0].name, r[1]) for r in inputs_table(result).rows] == [("stress", "120 MPa")]
    assert "Source" not in inputs_table(result).headers


def test_controlled_variables_keep_requirement_provenance():
    reqs = Requirements.loads('''[item]
id="PART"
[vars.P]
value=12
unit="kN"
description="Required load"
source="REQ-1"
''')
    table = inputs_table(controlled(reqs))
    assert table.rows[0][1:] == ("12 kN", "Required load; PART", "REQ-1")
    assert nomenclature(reqs).rows[0][1:] == ("Required load", "kN")


def test_document_nomenclature_can_precede_values_and_refreshes_on_rebuild():
    source = '''from kip import *
# %% table "Nomenclature"
nomenclature()
# %% inputs "Loads"
P = 2 * kN  # Applied load
L = 100 * mm  # Lever arm
# %% calc "Bending moment"
M = P * L  # -> kN*m
'''
    doc = build(source=source)
    rows = {r[0].name: r[1:] for r in doc.results["nomenclature"].content.rows}
    assert rows == {"P": ("Applied load", "kN"), "L": ("Lever arm", "mm"), "M": ("Bending moment", "kN⋅m")}
    pdf = pymupdf.open(stream=compile_pdf(emit(doc)), filetype="pdf")
    assert "Applied load" in "".join(p.get_text() for p in pdf)
    old = doc.results
    fresh = build(source=source.replace("# Applied load", "# Revised load"))
    fresh.namespace = {}
    execute(fresh)
    assert fresh.results["nomenclature"].content.rows[0][1] == "Revised load"
    assert doc.results["nomenclature"].content.rows[0][1] == "Applied load"


def test_legacy_dictionary_and_explicit_metadata_sources_still_work():
    assert nomenclature({"P": ("Load", "kN")}).rows[0][1:] == ("Load", "kN")
    assert len(nomenclature(constants()).rows) == 4
    assert inputs_table(constants()).rows[0][3] == "REQ-1"


def test_conflicting_symbol_dimensions_are_not_silently_merged():
    first = Constants().add("a", 1 * mm)
    second = Constants().add("a", 1 * kN)
    with pytest.raises(ValueError, match="incompatible units"):
        nomenclature(first, second)


@calculation
def with_default(c, factor=2):
    load = c.P
    c.P  # Repeated reads must not repeat the displayed row.
    # equations
    scaled = factor * load


@calculation
def conditional(c, switch=True):
    size = c.d
    if switch:
        size = c.t
    # equations
    area = size**2


def test_arguments_and_repeated_reads_do_not_repeat_execution():
    result = with_default(constants())
    table = inputs_table(result)
    assert [(r[0].name, r[1]) for r in table.rows] == [("factor", "2"), ("P", "12 kN")]
    assert result.scaled == 24 * kN


def test_conditional_reassignment_does_not_keep_the_wrong_description():
    result = conditional(constants())
    assert result.metadata["size"].description == ""
    assert {r[0].name for r in inputs_table(result).rows} == {"d", "t"}


def test_upstream_setup_alias_keeps_metadata_even_when_not_in_equations():
    @calculation
    def upstream(c):
        thickness = c.t
        diameter = c.d
        # equations
        area = diameter**2

    @calculation
    def downstream(previous):
        thickness = previous.thickness
        # equations
        size = 2 * thickness

    result = upstream(constants())
    assert "thickness" not in result.symbols
    table = inputs_table(downstream(result))
    assert table.rows[0][1:] == ("10 mm", "Plate thickness", "DWG-2")


def test_input_table_can_precede_calculation_and_export_its_actual_inputs(tmp_path):
    (tmp_path / "analysis.py").write_text('''from kip import *
events = []
@calculation
def run(c):
    events.append("ran")
    P = c.P
    # equations
    twice = 2 * P
''')
    source = '''from kip import *
import analysis
C = Constants().add("P", 12*kN, description="Load", source="REQ-1")
# %% table "Inputs"
inputs_table(result, xlsx="inputs.xlsx")
# %% calculation "Result"
result = analysis.run(C)
'''
    doc = build(path=tmp_path / "doc.py", source=source)
    assert doc.namespace["analysis"].events == ["ran"]
    pdf = pymupdf.open(render(doc))
    text = "".join(p.get_text() for p in pdf)
    assert text.index("INPUTS") < text.index("RESULT")
    assert "REQ-1" in text
    from openpyxl import load_workbook
    with_workbook = load_workbook(tmp_path / "output/inputs.xlsx", read_only=True)
    try:
        rows = list(with_workbook.active.values)
        assert rows[1] == ("P", "12 kN", "Load", "REQ-1")
    finally:
        with_workbook.close()


def test_conflicting_descriptions_require_an_explicit_choice():
    first = Constants().add("a", 1*mm, description="Length")
    second = Constants().add("a", 2*mm, description="Width")
    with pytest.raises(ValueError, match="conflicting descriptions"):
        nomenclature(first, second)
    table = nomenclature(first, second, overrides={"a": ("Dimension", "m")})
    assert table.rows[0][1:] == ("Dimension", "m")
