"""PDF geometry regressions: inspect baselines and painted vector bounds."""
import math
import pymupdf
import pytest

from kip.doc import build
from kip.render import emit
from kip.render.pdf import compile_pdf
from kip.render.layout import Layout, PageSpec, Position

SOURCE = '''from kip import *
# %% kip.text id=intro label="Introduction"
"""## Heading

Ordinary prose sits on the rules.
A second sentence wraps when space is narrow.

Another paragraph follows."""
# %% kip.given id=inputs label="Inputs"
a = 20
b = 3
# %% kip.calc id=calc label="Calculation"
c = a / b
# %% kip.draw id=sketch label="Sketch" caption="Drawing caption"
sketch = Drawing(width=80, body="circle((0,0), radius: 1)")
# %% kip.text id=last
"""Final paragraph after the drawing."""
'''


def pdf(source=SOURCE, **page):
    return pymupdf.open(stream=compile_pdf(emit(
        build(source=source, path="doc.py"), Layout(page=PageSpec(**page)))))


@pytest.mark.parametrize("step", [2, 4, 5, 6.35])
@pytest.mark.parametrize("frames", [False, True])
def test_pdf_baselines_follow_configured_grid(step, frames):
    doc = pdf(grid_step=step, frames=frames)
    checked = 0
    for page in doc:
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                for span in line["spans"]:
                    text = span["text"].strip()
                    # Prose/captions sit on rules; labels and values use centered cells.
                    if not any(t in text for t in ("Ordinary", "second sentence", "Another paragraph", "Final paragraph", "Drawing caption", "space is narrow")):
                        continue
                    y = span["origin"][1] * 25.4 / 72 - (279.4 % step) / 2
                    assert abs(y / step - round(y / step)) < 0.002, (text, y, step)
                    checked += 1
    assert checked >= 4


def test_options_roundtrip_and_reach_every_template():
    layout = Layout.loads('[page]\ngrid_step="0.25in"\nframes=true')
    assert Layout.loads(layout.dumps()).page.frames
    source = SOURCE.replace('id=sketch', 'id=sketch panel=true frame=false').replace(
        'id=last', 'id=last snap=false')
    files = emit(build(source=source, path="doc.py"), layout)
    main = files["main.typ"].decode()
    assert 'frames: true' in main and 'grid-step: 6.35mm' in main
    assert '#kip-drawing(frame: false, panel: true,' in main
    assert '#kip-text(snap: false,' in main
    compile_pdf(files)


@pytest.mark.parametrize("step", [0, -1, math.nan, math.inf])
def test_invalid_grid_size_rejected(step):
    with pytest.raises(ValueError, match="grid_step"):
        PageSpec(grid_step=step)


def test_drawing_panel_hugs_canvas_and_is_opt_in():
    source = '''from kip import *
# %% kip.draw id=d PANEL
canvas = Drawing(width=80, body="circle((0,0), radius: 1)")
'''
    def cards(toggle):
        d = pdf(source.replace("PANEL", toggle))
        return [item["rect"] for item in d[0].get_drawings()
                if item["fill"] and all(abs(a-b) < .001 for a,b in
                    zip(item["fill"], (253/255, 251/255, 244/255)))]
    assert not cards("")
    bounds = cards("panel=true")
    assert len(bounds) == 1
    assert 20 < bounds[0].width * 25.4 / 72 < 25


def test_manual_position_snaps_unless_explicitly_freeform():
    source = '# %% kip.text id=t FLAG\n"""Manual text."""'
    layout = Layout(blocks={"t": Position(15, 32, 100)})
    for flag, expected in [("", 37.2), ("snap=false", 32 + 7.5*25.4/72)]:
        doc = pymupdf.open(stream=compile_pdf(emit(
            build(source=source.replace("FLAG", flag), path="doc.py"), layout)))
        span = next(s for b in doc[0].get_text("dict")["blocks"] for l in b.get("lines", []) for s in l["spans"] if "Manual text" in s["text"])
        assert span["origin"][1] * 25.4/72 == pytest.approx(expected, abs=.01)

def test_long_prose_keeps_grid_across_page_breaks():
    source = '# %% kip.text id=t\n"""' + ('Many words fill this long paragraph. ' * 900) + 'END_SENTINEL."""'
    doc = pdf(source)
    assert len(doc) > 2
    assert 'END_SENTINEL' in doc[-1].get_text()
    for page in doc:
        lines = [line for b in page.get_text('dict')['blocks'] for line in b.get('lines', [])
                 if 'Many words' in ''.join(s['text'] for s in line['spans'])]
        assert lines
        for line in lines:
            y = line['spans'][0]['origin'][1] * 25.4 / 72 - 2.2
            assert y / 5 == pytest.approx(round(y / 5), abs=.002)


def test_plot_background_is_only_the_data_rectangle():
    source = '''from kip import *
# %% kip.plot id=p label="Plot title"
f = Figure(width=80, height=45, xlabel="Horizontal", ylabel="Vertical")
f.line([0, 1], [0, 1])
'''
    doc = pdf(source)
    cards = [item['rect'] for item in doc[0].get_drawings()
             if item['fill'] and all(abs(a-b) < .001 for a,b in
                 zip(item['fill'], (253/255, 251/255, 244/255)))]
    assert len(cards) == 1
    assert cards[0].width * 25.4/72 <= 80
    assert cards[0].height * 25.4/72 <= 45


def test_table_marker_options_are_not_lost():
    source = '''from kip import *
# %% kip.table id=t frame=false snap=false
t = Table(columns=["Name", "Value"], rows=[("a", 1)])
'''
    files = emit(build(source=source, path='doc.py'), Layout(page=PageSpec(frames=True)))
    assert '#kip-table(snap: false, frame: false,' in files['main.typ'].decode()
    compile_pdf(files)


def test_scaled_equations_keep_their_baseline():
    source = '''from kip import *
# %% kip.given id=i
a = 123456.789
# %% kip.calc id=c
b = a * a * a * a
'''
    layout = Layout(blocks={"i": Position(15, 15, 40), "c": Position(15, 40, 40)})
    doc = pymupdf.open(stream=compile_pdf(emit(build(source=source, path='doc.py'), layout)))
    equals = [span for b in doc[0].get_text('dict')['blocks'] for l in b.get('lines', [])
              for span in l['spans'] if '=' in span['text'] and span['origin'][1]*25.4/72 > 42.2 and abs(span['size'] - 8.2) > .01]
    assert equals
    for span in equals:
        y = span['origin'][1] * 25.4/72 - 2.2
        assert y/5 == pytest.approx(round(y/5), abs=.002)


@pytest.mark.parametrize("step", [4, 5, 6.35])
def test_plot_data_corners_are_grid_intersections(step):
    doc = pdf("""from kip import *
# %% kip.plot id=p
p = Figure(width=83, height=47, xlabel="Horizontal", ylabel="Vertical")
p.line([0, 1], [0, 1])
""", grid_step=step)
    cards = [d["rect"] for d in doc[0].get_drawings() if d["fill"] and
             all(abs(a-b) < .001 for a,b in zip(d["fill"], (253/255,251/255,244/255)))]
    assert len(cards) == 1
    for coordinate, origin in zip(cards[0], [(215.9 % step)/2, (279.4 % step)/2]*2):
        cells = (coordinate * 25.4/72 - origin) / step
        assert cells == pytest.approx(round(cells), abs=.002)


def test_equations_have_contiguous_numbers():
    doc = pdf()
    import re
    numbers = re.findall(r"\((\d+)\)", "".join(p.get_text() for p in doc))
    assert numbers == ["1"]


def test_furniture_rules_and_table_bounds_follow_grid():
    doc = pdf('# %% kip.text id=t\n"""Body."""', title="Title", author="Author", revision="B", date="2026-09-13", marking="CIPS Proprietary")
    page = doc[0]
    assert "Author" in page.get_text() and "CIPS PROPRIETARY" in page.get_text()
    rules = [d["rect"] for d in page.get_drawings() if d["rect"].width > 400 and d["rect"].height < .1]
    assert len(rules) == 2
    for rect in rules:
        for value, offset in [(rect.x0, .45), (rect.x1, .45), (rect.y0, 2.2)]:
            cells = (value*25.4/72 - offset)/5
            assert cells == pytest.approx(round(cells), abs=.002)


def test_furniture_uses_second_rows_and_title_rule_stops_before_fields():
    doc = pdf('# %% kip.text id=t\n"""Body."""', title="A title that wraps naturally in the available left column",
              subtitle="Subtitle", header_left="Running head", author="Author", marking="CIPS Proprietary")
    page = doc[0]
    spans = [s for b in page.get_text("dict")["blocks"] for l in b.get("lines", []) for s in l["spans"]]
    head = next(s for s in spans if s["text"] == "Running head")
    footer = next(s for s in spans if "of 1" in s["text"])
    assert 7.2 < head["origin"][1]*25.4/72 < 12.2
    assert 267.2 < footer["origin"][1]*25.4/72 < 272.2
    rules = [d["rect"] for d in page.get_drawings() if d["rect"].height < .1 and 250 < d["rect"].width < 400]
    assert len(rules) == 1
    # Metadata table starts at 140.45 mm; three 5 mm cells separate it from the rule.
    assert rules[0].x1*25.4/72 == pytest.approx(125.45, abs=.01)
    assert "available left column" in page.get_text().replace("\n", " ")


def test_flow_can_switch_between_single_and_two_columns():
    from kip.render.pdf import block_geometry
    source = '\n'.join(f'# %% kip.text id=t{i} ' + ('columns=2' if i == 1 else 'columns=1' if i == 5 else '') +
                       '\n"""' + ('Paragraph words. ' * 35) + '"""' for i in range(6))
    files = emit(build(source=source, path="doc.py"), Layout())
    geo = {g.id: g for g in block_geometry(files)}
    assert geo["t0"].x == pytest.approx(15.45, abs=.01)
    assert geo["t5"].x == pytest.approx(15.45, abs=.01)
    rendered = pymupdf.open(stream=compile_pdf(files))
    assert any(s["origin"][0] * 25.4/72 > 100 for page in rendered
               for b in page.get_text("dict")["blocks"] for line in b.get("lines", [])
               for s in line["spans"] if "Paragraph" in s["text"])
    assert all((geo[f"t{i}"].x - .45)/5 == pytest.approx(round((geo[f"t{i}"].x - .45)/5), abs=.002) for i in range(6))


def test_table_gives_prose_more_width_than_identifiers():
    doc = pdf('''from kip import *
# %% kip.table id=t
t = Table(columns=[Column("id", "ID", align="left"), Column("requirement", "Requirement", align="left"), Column("status", "Status", align="left")],
 rows=[("R-001", "The component shall withstand the specified design load with a positive margin of safety.", "PASS")])
''')
    spans = [s for b in doc[0].get_text("dict")["blocks"] for l in b.get("lines", []) for s in l["spans"]]
    x = {s["text"]: s["bbox"][0] for s in spans}
    assert x["Status"] - x["Requirement"] > 2 * (x["Requirement"] - x["ID"])
    text = doc[0].get_text().replace("\n", " ")
    assert "positive margin of safety." in text and "PASS" in text


def test_opening_text_wraps_beside_title_fields_then_returns_full_width():
    words = [f"word{i:03}" for i in range(95)]
    source = '# %% kip.text id=scope label="Scope" wrap_title=true\n"""' + ' '.join(words) + '"""'
    doc = pdf(source, title="Title", subtitle="Subtitle", project="Project", document="DOC-1",
              author="Author", checker="Checker", revision="B", date="2026-09-13")
    page = doc[0]
    text = page.get_text()
    for word in words:
        assert text.count(word) == 1
    lines = [line for b in page.get_text("dict")["blocks"] for line in b.get("lines", [])
             if any("word" in s["text"] for s in line["spans"])]
    assert lines[0]["bbox"][1]*25.4/72 < 47.2  # starts alongside the metadata table
    assert any(line["bbox"][2]*25.4/72 > 145 for line in lines)  # expands below it
    for line in lines:
        y = line["spans"][0]["origin"][1]*25.4/72 - 2.2
        assert y/5 == pytest.approx(round(y/5), abs=.002)
