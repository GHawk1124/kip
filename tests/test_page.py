"""Page furniture: margins, running head, markings and the title block."""
import pymupdf
import pytest

from kip.doc import build
from kip.render import emit, render
from kip.render.emitter import emit_body
from kip.render.emitter import emit_debug
from kip.render.layout import Layout, PageSpec, Position, auto_layout

DOC = '''from kip import *

# %% kip.given id=g label="Inputs"
P = 2.5 * kN

# %% kip.calc id=c result_unit=kN*m label="Moment"
M = P * 300 * mm
'''


def spec(**kw) -> PageSpec:
    return PageSpec(title="T", **kw)


def test_freeform_coordinates_are_page_absolute(tmp_path):
    """`place` is relative to the content box, so the margin must be removed.

    Without this the whole document renders one margin too far down and right.
    """
    lay = Layout(page=spec(margin=15.0, grid_step=5.0))
    lay.blocks["g"] = Position(x=15.0, y=15.0, w=80.0, page=1)
    doc = build(source=DOC, path="doc.py")
    out = emit_debug(doc, lay)
    assert "dx: -0.45mm" in out and "dy: 0mm" in out

    lay.blocks["g"] = Position(x=115.0, y=65.0, w=80.0, page=1)
    out = emit_debug(doc, lay)
    assert "dx: 99.55mm" in out and "dy: 50mm" in out


def test_margin_snaps_to_the_grid():
    """Content can only ride the printed grid if its origin is on it."""
    assert spec(margin=16.0, grid_step=5.0).snapped_margin() == 15.0
    assert spec(margin=18.0, grid_step=5.0).snapped_margin() == 20.0
    # with the grid off the margin is taken literally
    assert spec(margin=16.0, grid=False).snapped_margin() == 16.0


def test_blocks_are_placed_on_their_own_page():
    """Placed content does not flow, so pages need explicit breaks."""
    lay = Layout(page=spec(margin=15.0))
    lay.blocks["g"] = Position(x=15.0, y=15.0, w=80.0, page=1)
    lay.blocks["c"] = Position(x=15.0, y=15.0, w=80.0, page=2)
    doc = build(source=DOC, path="doc.py")
    out = emit_debug(doc, lay)
    assert out.count("#pagebreak()") == 1


def test_marking_appears_on_every_page():
    doc = build(source=DOC, path="doc.py")
    out = emit_debug(doc, Layout(page=spec(marking="CUI")))
    assert 'marking: "CUI"' in out


def test_running_head_defaults_from_title_and_author():
    p = spec(author="G. Comes", revision="B", date="2026-09-13")
    assert p.resolved_header_left() == "T"
    right = p.resolved_header_right()
    assert "G. Comes" in right and "Rev B" in right and "2026-09-13" in right


def test_running_head_can_be_overridden():
    p = spec(author="A", header_left="LEFT", header_right="RIGHT")
    assert p.resolved_header_left() == "LEFT"
    assert p.resolved_header_right() == "RIGHT"


def test_footer_defaults_to_project_and_document():
    p = spec(project="P-1", document="CALC-001")
    assert "P-1" in p.resolved_footer_left()
    assert "CALC-001" in p.resolved_footer_left()


def test_title_block_fields_are_ordered_and_skip_blanks():
    p = spec(project="P", author="A", revision="B", extra_fields={"scale": "1:2"})
    fields = p.title_fields()
    assert fields == [("project", "P"), ("author", "A"), ("rev", "B"),
                      ("scale", "1:2")]


def test_page_furniture_round_trips_through_layout_toml(tmp_path):
    lay = Layout(page=spec(
        marking="Proprietary", author="G. Comes", project="P-1",
        document="D-1", revision="B", date="2026-09-13", client="C",
        checker="A. Ruiz", header_left="HL", footer_left="FL",
    ))
    path = lay.save(tmp_path / "layout.toml")
    back = Layout.load(path)
    for attr in ("marking", "author", "project", "document", "revision",
                 "date", "client", "checker", "header_left", "footer_left"):
        assert getattr(back.page, attr) == getattr(lay.page, attr), attr


def test_marking_text_reaches_the_pdf(tmp_path):
    doc = build(source=DOC, path="doc.py")
    doc.path = tmp_path / "doc.py"
    out = render(doc, "o.pdf",
                 layout=Layout(page=spec(marking="Proprietary")))
    # the banner is letter-spaced, so extraction yields "P R O P R I E TA R Y"
    text = "".join(pymupdf.open(out)[0].get_text().split()).upper()
    assert text.count("PROPRIETARY") >= 2, "top and bottom banner"


def test_title_block_values_reach_the_pdf(tmp_path):
    doc = build(source=DOC, path="doc.py")
    doc.path = tmp_path / "doc.py"
    out = render(doc, "o.pdf",
                 layout=Layout(page=spec(author="G. Comes", document="CALC-9")))
    text = pymupdf.open(out)[0].get_text()
    assert "G. Comes" in text and "CALC-9" in text


def test_pagebreak_after_ends_a_section_without_marking_the_next_one():
    source = '''from kip import *
# %% text a "A" pagebreak=after
"""First section."""

# %% text b "B"
"""Second section, on its own page."""
'''
    out = emit_body(build(source=source))
    assert out.index("#pagebreak(weak: true)") > out.index("First section")
    assert out.index("#pagebreak(weak: true)") < out.index("Second section")


def test_a_trailing_pagebreak_after_adds_no_empty_page():
    out = emit_body(build(source='from kip import *\n# %% text a "A" pagebreak=after\n"""Only."""\n'))
    assert "#pagebreak" not in out


def test_pagebreak_after_closes_the_column_block_first():
    source = '''from kip import *
# %% text a "A" columns=2
"""Left."""

# %% text b "B" pagebreak=after
"""Right."""

# %% text c "C"
"""Next page."""
'''
    out = emit_body(build(source=source))
    # the break must come after the closing bracket, never inside #columns(...)[
    assert "]\n#pagebreak(weak: true)" in out


def test_pagebreak_both_breaks_on_each_side():
    source = '''from kip import *
# %% text a "A"
"""One."""

# %% text b "B" pagebreak=both
"""Alone."""

# %% text c "C"
"""Three."""
'''
    assert emit_body(build(source=source)).count("#pagebreak(weak: true)") == 2


def test_an_unknown_pagebreak_value_is_rejected():
    with pytest.raises(ValueError, match="pagebreak must be one of"):
        emit_body(build(source='from kip import *\n# %% text a "A" pagebreak=maybe\n"""X."""\n'))


SECTIONS = '''from kip import *
# %% text a "Requirements" section=1
"""One."""

# %% text b "Interpretation" section=2
"""One point one."""

# %% text c "Weld rim" section=3
"""One point one point one."""

# %% text d "Land face" section=4
"""Four deep."""

# %% text e "Architecture" section=1
"""Two."""
'''


def _rendered(tmp_path, source, **kw):
    doc = build(source=source, path="doc.py")
    doc.path = tmp_path / "doc.py"
    return pymupdf.open(render(doc, "s.pdf", **kw))


def test_sections_number_themselves_to_any_depth(tmp_path):
    page = _rendered(tmp_path, SECTIONS)[0]
    text = page.get_text()
    for number, title in (("1", "Requirements"), ("1.1", "Interpretation"),
                          ("1.1.1", "Weld rim"), ("1.1.1.1", "Land face"),
                          ("2", "Architecture")):
        assert f"{number} {title}" in text


def test_sections_become_the_pdf_outline(tmp_path):
    assert [(level, title) for level, title, _
            in _rendered(tmp_path, SECTIONS).get_toc()] == [
        (1, "1 Requirements"), (2, "1.1 Interpretation"), (3, "1.1.1 Weld rim"),
        (4, "1.1.1.1 Land face"), (1, "2 Architecture"),
    ]


def test_a_section_label_is_not_also_printed_as_a_block_title():
    out = emit_body(build(source=SECTIONS))
    assert "#kip-section(1)[Requirements]" in out
    assert 'label: "Requirements"' not in out


def test_the_numbering_pattern_is_configurable(tmp_path):
    text = _rendered(tmp_path, SECTIONS,
                     layout=Layout(page=PageSpec(section_numbering="I.A")))[0].get_text()
    assert "I Requirements" in text and "I.A Interpretation" in text

    text = _rendered(tmp_path, SECTIONS,
                     layout=Layout(page=PageSpec(section_numbering="")))[0].get_text()
    assert "Requirements" in text and "1 Requirements" not in text


def test_a_wrapped_opening_section_does_not_start_the_count_short(tmp_path):
    source = '''from kip import *
# %% text a "Scope" section=1
"""Opening prose wrapped beside the title block."""

# %% text b "Detail" section=2
"""Under it."""
'''
    text = _rendered(tmp_path, source,
                     layout=Layout(page=PageSpec(title="T")))[0].get_text()
    assert "1 Scope" in text and "1.1 Detail" in text


def test_a_section_without_a_label_says_what_is_missing():
    with pytest.raises(ValueError, match="needs a label"):
        emit_body(build(source='from kip import *\n# %% text a section=1\n"""X."""\n'))


def test_a_nonsense_section_level_is_rejected():
    with pytest.raises(ValueError, match="whole number"):
        emit_body(build(source='from kip import *\n# %% text a "A" section=deep\n"""X."""\n'))
    with pytest.raises(ValueError, match="1 or more"):
        emit_body(build(source='from kip import *\n# %% text a "A" section=0\n"""X."""\n'))


def test_a_semicolon_after_a_citation_survives(tmp_path):
    source = '''from kip import *
refs = Sources(fm=Source(title="Fluid Mechanics"))
# %% text a "Basis"
"""The minor-loss form @src:fm; the coefficient is assumed."""

# %% sources refs "References"
'''
    text = _rendered(tmp_path, source)[0].get_text()
    assert "; the coefficient is assumed" in text
