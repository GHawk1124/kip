import pytest
from typer.testing import CliRunner

from kip.cli import app
from kip.doc import build
from kip.render import emit, compile_pdf
from kip.render.diagnostics import RenderError


@pytest.mark.parametrize("opening", [False, True])
def test_typst_error_points_to_multiline_prose_in_original_document(opening):
    source = '''from kip import *
report = run_document(__file__, title="Example")
# %% text notes "Notes" wrap_title=WRAP
r"""
Some prose.
#nosuchfunction()
"""
'''.replace("WRAP", str(opening).lower())
    with pytest.raises(RenderError) as caught:
        compile_pdf(emit(build(path="doc.py", source=source)))
    assert caught.value.locations[0] == ("doc.py", "notes", 6)
    assert "unknown variable" in str(caught.value)
    assert "main.typ:" in caught.value.diagnostic


def test_generated_plot_error_points_to_its_authoring_cell():
    source = '''from kip import *
# %% plot "Bad plot"
plot([0, 1], [0, 1], xlabel=Math("nosuchsymbol"))
'''
    with pytest.raises(RenderError) as caught:
        compile_pdf(emit(build(path="doc.py", source=source)))
    assert caught.value.locations[0] == ("doc.py", "bad_plot", 3)


def test_check_renders_by_default_and_does_not_export(tmp_path):
    path = tmp_path / "doc.py"
    path.write_text('# %% text notes "Notes"\n"#nosuchfunction()"')
    runner = CliRunner()
    assert runner.invoke(app, ["check", str(path), "--no-render"]).exit_code == 0
    checked = runner.invoke(app, ["check", str(path)])
    assert checked.exit_code == 1
    assert f"{path}:2: error: [notes] Typst:" in checked.output
    assert not (tmp_path / "output").exists()
    path.write_text('from kip import *\n# %% table "Data"\nTable(["Item"], [(1,)], xlsx="data.xlsx")')
    assert runner.invoke(app, ["check", str(path), "--render"]).exit_code == 0
    assert not (tmp_path / "output").exists()


def test_seeded_document_names_are_not_spurious_warnings(tmp_path):
    path = tmp_path / "doc.py"
    path.write_text('from kip import *\nreport = run_document(__file__)\n# %% text "Notes"\n"Prose"')
    checked = CliRunner().invoke(app, ["check", str(path), "--render"])
    assert checked.exit_code == 0 and "undefined" not in checked.output


@pytest.mark.parametrize("columns", [1, 2])
def test_long_working_and_page_breaks_render_within_page_bounds(columns):
    import pymupdf
    from kip.render.layout import Layout, PageSpec

    source = '''from kip import *
# %% inputs "Loads"
P = 12*kN
L = 200*mm
e = 25*mm
# %% calc "Moment"
M = P * (L + e)  # -> kN*m
# %% text "Further work" pagebreak=before
"""- First task
- Another task that wraps across a narrow column while keeping its hanging indent.
"""
# %% table "Data"
Table(["Item", "Description"], [(f"ROW-{i:03}", "Recorded result") for i in range(75)])
'''
    pdf = pymupdf.open(stream=compile_pdf(emit(build(source=source), Layout(page=PageSpec(columns=columns)))), filetype="pdf")
    assert len(pdf) >= 2
    assert "Further work" not in pdf[0].get_text()
    text = "".join(p.get_text() for p in pdf)
    for i in range(75):
        assert text.count(f"ROW-{i:03}") == 1
    for page in pdf:
        for x0, y0, x1, y1, *_ in page.get_text("words"):
            assert 0 <= x0 < x1 <= page.rect.width
            assert 0 <= y0 < y1 <= page.rect.height


def test_wide_plot_fits_a_two_column_document():
    import pymupdf
    source = '''from kip import *
report = run_document(__file__, columns=2)
# %% plot "Load history"
plot([0, 1, 2], [0, 10, 20], xlabel="Time (s)", ylabel="Force (N)", width=150)
# %% text "Notes"
"The plot must stay within its column."
'''
    pdf = pymupdf.open(stream=compile_pdf(emit(build(source=source))))
    # Includes axis text and the vector plot frame, not just the authoring label.
    for page in pdf:
        for x0, y0, x1, *_ in page.get_text("words"):
            if y0 * 25.4 / 72 > 260:  # Page furniture stays full width.
                continue
            assert 15 <= x0 * 25.4 / 72 < x1 * 25.4 / 72 <= 101
        assert all(d["rect"].x1 <= page.rect.width for d in page.get_drawings())


def test_short_two_column_passage_can_break_before_a_cell_and_its_heading():
    from kip.render.pdf import block_geometry
    source = '''
# %% text "Left" columns=2 section=1
"Left paragraph."
# %% text "Right" columnbreak=true section=1
"Right paragraph."
# %% text "Below" columns=default
"Full width again."
'''
    files = emit(build(source=source))
    geo = {g.id: g for g in block_geometry(files)}
    assert geo["left"].page == geo["right"].page == geo["below"].page
    assert geo["right"].x - geo["left"].x > 90
    assert geo["right"].y == pytest.approx(geo["left"].y)
    assert geo["below"].x == pytest.approx(geo["left"].x)
    assert geo["below"].y > geo["right"].y
    with pytest.raises(ValueError, match="requires two-column"):
        emit(build(source=source.replace("columns=2", "columns=1")))


@pytest.mark.parametrize("columns", [1, 2])
def test_wrapped_table_cells_stay_inside_their_painted_rows(columns):
    import pymupdf
    from kip.render.layout import Layout, PageSpec
    source = '''from kip import *
# %% table "Overview"
Table(["Section", "State", "Outstanding work"], [
    ("Preliminary Analysis", "PRESENT", ""),
    ("Manufacturing", "N/A", "Explicitly excluded in packet settings."),
    ("Compliance", "PASS", "All local requirements verified."),
])
'''
    pdf = pymupdf.open(stream=compile_pdf(emit(build(source=source), Layout(page=PageSpec(columns=columns)))))
    page = pdf[0]
    cards = [d["rect"] for d in page.get_drawings() if d.get("fill") and d["rect"].width > 200]
    final_word = page.search_for("verified.")[0]
    assert any(card.contains(final_word) for card in cards)
