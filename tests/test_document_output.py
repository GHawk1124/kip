from pathlib import Path

import pytest

from kip.doc import build
from kip.render.pdf import render


def test_all_artifacts_are_relative_to_document(tmp_path, monkeypatch):
    source_dir = tmp_path / "project"
    source_dir.mkdir()
    source = '''from kip import *
# %% kip.table id=t
t = Table(columns=["A"], rows=[(1,)], xlsx="data.xlsx")
# %% kip.draw id=d
d = Drawing(svg=b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><path d="M0 0L10 10" stroke="black"/></svg>', attachments={"face.dxf": b"test export"})
'''
    doc = build(source=source, path=source_dir / "doc.py")
    monkeypatch.chdir(tmp_path)
    out = render(doc)
    assert out == source_dir / "output" / "project.pdf"
    assert (out.parent / "data.xlsx").is_file()
    assert (out.parent / "face.dxf").read_bytes() == b"test export"
    assert (out.parent / "drawings" / "d.svg").is_file()
    assert not (tmp_path / "output").exists()


def test_output_and_workbook_cannot_escape_output_folder(tmp_path):
    doc = build(source='# %% kip.text id=t\n"""Text."""', path=tmp_path / "doc.py")
    for target in ("../escape.pdf", tmp_path / "escape.pdf"):
        with pytest.raises(ValueError, match="output"):
            render(doc, target)
    source = 'from kip import *\n# %% kip.table id=t\nt=Table(columns=["A"], rows=[(1,)], xlsx="../escape.xlsx")'
    doc = build(source=source, path=tmp_path / "doc.py")
    with pytest.raises(ValueError, match="workbook"):
        render(doc)
