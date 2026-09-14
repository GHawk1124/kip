from pathlib import Path
import subprocess
import sys

import pymupdf
import pytest

from kip import Sources, build_pdf, calculation, mm, N, read_records
from kip.doc import build
from kip.render import emit
from kip.render.pdf import compile_pdf


@calculation(units={"stress": "MPa"})
def stress_model(force, diameter):
    # equations
    area = 3.141592653589793 * diameter**2 / 4
    stress = force / area
    return locals()


def test_external_equations_keep_values_and_render_math(tmp_path):
    answer = stress_model(100 * N, 10 * mm)
    assert answer.stress.magnitude == pytest.approx(1.2732395447)
    document = build(source='''import test_executable as analysis
from kip import *
# %% calculation strength "Strength"
answer = analysis.stress_model(100 * N, 10 * mm)
''', path=tmp_path / "doc.py")
    data = compile_pdf(emit(document))
    text = "".join(p.get_text() for p in pymupdf.open(stream=data, filetype="pdf"))
    assert "Calculation(" not in text and "1.273" in text
    assert "area" in document.results["strength"].latex


def test_direct_script_cli_and_relative_sources(tmp_path):
    (tmp_path / "sources.toml").write_text('[sources.test]\ntitle="Reference example"\n')
    path = tmp_path / "doc.py"
    path.write_text('''from kip import *
report = run_document(__file__, title="Executable report", author="Author", output="report.pdf")
# %% text intent "Design intent"
"""Editable opening text. @src:test"""
# %% sources references "References"
refs = Sources.load()
''')
    run = subprocess.run([sys.executable, str(path)], cwd=tmp_path.parent, capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    assert (tmp_path / "output/report.pdf").is_file()
    out = build_pdf(path)
    pdf = pymupdf.open(out)
    text = "".join(p.get_text() for p in pdf)
    assert "Executable report" in text and "Reference example" in text
    emitted = emit(build(path))["main.typ"].decode()
    assert 'intro: (id: "intent"' in emitted


def test_records_validate_inputs_and_close_workbook(tmp_path):
    from openpyxl import Workbook
    path = tmp_path / "inputs.xlsx"
    book = Workbook()
    book.active.title = "Inputs"
    book.active.append(["key", "value"])
    book.active.append(["flow", 0.14])
    book.save(path)
    assert read_records(path) == [{"key":"flow", "value":0.14}]
    book.active["B2"] = "=1/2"
    book.save(path)
    with pytest.raises(ValueError, match="formulas"):
        read_records(path)


def test_sources_missing_file_is_not_silently_empty(tmp_path):
    with pytest.raises(FileNotFoundError):
        Sources.load(tmp_path / "missing.toml")


def test_local_analysis_imports_are_project_scoped(tmp_path):
    for name, value in [("first", 10), ("second", 20)]:
        folder = tmp_path / name
        folder.mkdir()
        (folder / "analysis.py").write_text(f"value = {value}\n")
        document = folder / "doc.py"
        document.write_text("import analysis\nx = analysis.value\n# %% calc result\ny = x\n")
        assert build(document).value("x") == value
