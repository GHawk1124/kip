from pathlib import Path
import tomllib
import unicodedata

import pymupdf
import pytest
import sympy as sp
from openpyxl import load_workbook
from typer.testing import CliRunner

from kip import Column, Math, Symbol, Table, build_pdf, nomenclature, plot
from kip.cli import app, _watch_stamp
from kip.doc import build
from kip.doc.loader import parse, replace_body, KipSyntaxError
from kip.render import emit
from kip.render.pdf import compile_pdf
from kip.scaffold import create_project


def test_shorthand_matches_legacy_execution_and_editing():
    source = '''from kip import *
# %% inputs loads "Applied loads"
P = 2 * kN
L = 100 * mm
# %% calc moment "Moment" unit=kN*m
M = P * L
'''
    doc = build(source=source)
    assert doc.value("M").magnitude == pytest.approx(0.2)
    assert not doc.warnings
    blocks = parse(source)
    assert blocks[-1].meta == {"label": "Moment", "result_unit": "kN*m"}
    edited = replace_body(source, blocks[-1], "M = P * L * 2")
    assert build(source=edited).value("M").magnitude == pytest.approx(0.4)


def test_shorthand_bad_quotes_have_source_location():
    with pytest.raises(KipSyntaxError, match="doc.py:1"):
        parse('# %% calc moment "Unclosed', "doc.py")
    assert parse('# %% text section "Section at Y = 0"')[0].meta["label"] == "Section at Y = 0"


def test_math_cells_compile_and_export_without_interpreting_prose(tmp_path):
    source = '''from kip import *
import sympy as sp
# %% table symbols "Nomenclature"
symbols = nomenclature({"sigma_br": ("Bearing # stress [safe]", "MPa")})
# %% table mixed "Other table"
mixed = Table([Column("symbol", Symbol("sigma_y")), "Meaning"], [
    (Symbol("P_d"), "literal_underscore"),
    (Math("x^2"), "power"),
    (sp.Symbol("alpha")**2, "sympy"),
])
'''
    document = build(source=source, path=tmp_path / "doc.py")
    pdf = pymupdf.open(stream=compile_pdf(emit(document)), filetype="pdf")
    text = unicodedata.normalize("NFKC", "".join(page.get_text() for page in pdf))
    assert "\u03c3" in text and "Bearing # stress [safe]" in text
    assert "literal_underscore" in text and "sigma_br" not in text
    # Subscript really is below the base glyph, not merely a substituted string.
    chars = [c for page in pdf for block in page.get_text("rawdict")["blocks"]
             if "lines" in block for line in block["lines"] for span in line["spans"]
             for c in span["chars"]]
    sigma = next(c for c in chars if unicodedata.normalize("NFKC", c["c"]) == "\u03c3")
    nearby = [c for c in chars if 0 < c["origin"][0] - sigma["origin"][0] < 15
              and 0 < c["origin"][1] - sigma["origin"][1] < 8]
    assert any(c["c"] == "b" for c in nearby)
    table = document.results["mixed"].content
    workbook = load_workbook(table.to_xlsx(tmp_path / "math.xlsx"))
    assert workbook.active["A1"].value == "sigma_y"
    assert workbook.active["A2"].value == "P_d"


def test_record_table_and_generator_plot():
    table = Table.from_records([{"Name": "a", "Value": 1}, {"Value": 2, "Name": "b"}])
    assert table.rows == [["a", 1], ["b", 2]]
    fig = plot((x for x in range(3)), (x*x for x in range(3)))
    assert fig.series[0].x == [0, 1, 2]
    assert fig.series[0].y == [0, 1, 4]
    with pytest.raises(ValueError, match="same length"):
        plot([1], [1, 2])
    with pytest.raises(ValueError, match="expected 2 cells"):
        Table(["a", "b"], [[1]])
    with pytest.raises(ValueError, match="same keys"):
        Table.from_records([{"a": 1}, {"b": 2}])


def test_inputs_named_like_exported_units_are_visible_and_cached():
    from kip.doc.kernel import execute

    document = build(source='''from kip import *
# %% inputs geometry "Geometry"
A = 200 * mm**2
L = 100 * mm
''')
    values = document.results["geometry"].values
    assert set(values) == {"A", "L"}
    pdf = pymupdf.open(stream=compile_pdf(emit(document)), filetype="pdf")
    text = "".join(page.get_text() for page in pdf)
    assert "200" in text and "100" in text and "GEOMETRY" in text
    previous = document.results
    document.namespace = {}
    execute(document, previous=previous)
    assert document.value("A").magnitude == 200
    assert document.value("L").magnitude == 100


@pytest.mark.parametrize("template", ["basic", "requirements"])
def test_generated_project_builds_from_another_working_directory(tmp_path, monkeypatch, template):
    root = tmp_path / template
    create_project(root, title='A "quoted" title', template=template)
    project = tomllib.loads((root / "pyproject.toml").read_text())
    assert project["project"]["description"] == 'A "quoted" title'
    assert (root / ".agents/skills/kip-authoring/SKILL.md").exists()
    monkeypatch.chdir(tmp_path)
    output = build_pdf(root)
    assert output.parent == root / "output"
    assert output.stat().st_size > 1000
    runner = CliRunner()
    assert runner.invoke(app, ["check", str(root)]).exit_code == 0
    if template == "requirements":
        assert (root / "output/verification.xlsx").exists()


def test_cli_skill_export_and_project_protection(tmp_path):
    runner = CliRunner()
    displayed = runner.invoke(app, ["skill"])
    assert displayed.exit_code == 0 and displayed.stdout.startswith("---\n")
    target = tmp_path / "SKILL.md"
    assert runner.invoke(app, ["skill", "-o", str(target)]).exit_code == 0
    assert target.read_text(encoding="utf-8").strip() == displayed.stdout.strip()
    assert runner.invoke(app, ["skill", "-o", str(target)]).exit_code == 1
    existing = tmp_path / "file"
    existing.write_text("keep me")
    assert runner.invoke(app, ["new", str(existing), "--no-sync"]).exit_code == 1
    assert existing.read_text() == "keep me"


def test_preview_builds_before_opening(tmp_path, monkeypatch):
    create_project(tmp_path / "doc")
    opened = []
    monkeypatch.setattr("kip.cli.typer.launch", lambda path: opened.append(path) or 0)
    result = CliRunner().invoke(app, ["preview", str(tmp_path / "doc")])
    assert result.exit_code == 0, result.output
    assert len(opened) == 1 and Path(opened[0]).is_file()


def test_watch_tracks_requirements_and_ignores_exports(tmp_path):
    req = tmp_path / "requirements.toml"
    req.write_text("a=1")
    before = _watch_stamp(tmp_path)
    (tmp_path / "output").mkdir()
    (tmp_path / "output/export.xlsx").write_text("ignored")
    assert _watch_stamp(tmp_path) == before
    req.write_text("a=2")
    assert _watch_stamp(tmp_path) != before
