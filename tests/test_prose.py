"""Compile authored Typst and check list geometry, not just emitted strings."""
import unicodedata

import pymupdf
import pytest

from kip.doc import build
from kip.render import emit
from kip.render.emitter import _markdown_to_typst
from kip.render.layout import Layout, PageSpec
from kip.render.pdf import compile_pdf


def render(prose, **page):
    source = '# %% text "Notes"\n' + repr(prose)
    files = emit(build(source=source), Layout(page=PageSpec(**page)))
    return pymupdf.open(stream=compile_pdf(files), filetype="pdf")


def spans(pdf):
    return [s for p in pdf for b in p.get_text("dict")["blocks"]
            for line in b.get("lines", []) for s in line["spans"]]


def test_native_typst_is_not_rewritten_as_markdown_headings():
    prose = '''#set text(fill: rgb("#123a6b"))
#let word = [Native code]
#strong[#word]
#list([Function bullet], [Another bullet])
#enum(start: 3, [Third step], [Fourth step])

## Real heading

```typst
# Literal heading
#list([Literal example])
```
'''
    converted = _markdown_to_typst(prose)
    assert "== Real heading" in converted
    assert "# Literal heading" in converted
    assert "#list([Literal example])" in converted
    pdf = render(prose)
    text = unicodedata.normalize("NFKC", "".join(p.get_text() for p in pdf))
    for expected in ("Native code", "Function bullet", "3.", "Third step",
                     "4.", "Fourth step", "Real heading", "# Literal heading"):
        assert expected in text
    assert next(s for s in spans(pdf) if s["text"] == "Native code")["color"] == 0x123A6B


@pytest.mark.parametrize("step", [2, 5, 6.35])
@pytest.mark.parametrize("marker", ["-", "+"])
def test_list_markers_wrapping_and_nested_items_follow_grid(step, marker):
    prose = f'''Before.

{marker} First item
{marker} A long item with enough words to wrap onto several lines in a narrow document column, preserving the hanging indentation.
  {marker} Nested item
  {marker} Another nested item
{marker} Last item

After.
'''
    pdf = render(prose, grid_step=step, columns=2)
    content = [s for s in spans(pdf) if s["origin"][1] > 40 and "of 1" not in s["text"] and s["text"] != "NOTES"]
    assert len(content) > 10
    for s in content:
        y = s["origin"][1] * 25.4 / 72 - (279.4 % step) / 2
        assert y / step == pytest.approx(round(y / step), abs=.002), s["text"]
    first = next(s for s in content if s["text"] == "First item")
    nested = next(s for s in content if s["text"] == "Nested item")
    assert nested["origin"][0] > first["origin"][0]
    # A wrapped continuation shares the text indent, not the bullet's column.
    long = next(s for s in content if s["text"].startswith("A long item"))
    continuation = next(s for s in content if "document column" in s["text"])
    assert continuation["origin"][0] == pytest.approx(long["origin"][0], abs=.02)


def test_long_list_flows_across_pages_without_losing_or_repeating_items():
    prose = "\n".join(f"- Item {i:03d}" for i in range(150))
    pdf = render(prose)
    assert len(pdf) >= 3
    text = "".join(p.get_text() for p in pdf)
    for i in range(150):
        assert text.count(f"Item {i:03d}") == 1


@pytest.mark.parametrize("font_size", [9, 10, 11])
@pytest.mark.parametrize("marker", ["-", "+"])
def test_wrapped_nested_list_does_not_shift_following_paragraphs_or_cells(font_size, marker):
    source = f'''# %% text "Notes"
"""Before the list.

{marker} First item.
  {marker} Nested item with enough words to wrap onto multiple lines inside the narrow document column.
    {marker} A deeper nested item that also wraps over multiple lines and must preserve the baseline spacing.
{marker} Last item.

After the list, another paragraph also wraps across this column.
"""
# %% text "Later"
"Following cell paragraph."
'''
    pdf = pymupdf.open(stream=compile_pdf(emit(build(source=source), Layout(page=PageSpec(columns=2, font_size=font_size)))))
    for span in spans(pdf):
        if span["text"] in ("NOTES", "LATER", "1 of 1"):
            continue
        y = span["origin"][1] * 25.4 / 72 - 2.2
        assert y / 5 == pytest.approx(round(y / 5), abs=.002), span["text"]


def test_lists_in_opening_text_keep_their_content_and_spacing():
    pdf = render("Opening.\n\n- Alpha\n- Beta\n\nClosing.",
                 title="A title", author="Engineering", project="Project",
                 document="DOC-1", revision="A", date="2026-09-20")
    text = "".join(p.get_text() for p in pdf)
    for word in ("Opening.", "Alpha", "Beta", "Closing."):
        assert text.count(word) == 1
    alpha, beta = (next(s for s in spans(pdf) if s["text"] == word) for word in ("Alpha", "Beta"))
    assert beta["origin"][1] - alpha["origin"][1] == pytest.approx(5 * 72 / 25.4, abs=.01)


@pytest.mark.parametrize("marker", ["-", "+"])
def test_blank_lines_between_list_items_add_one_grid_row(marker):
    distances = []
    for separator in ("\n", "\n\n"):
        pdf = render(f"{marker} Alpha{separator}{marker} Beta")
        alpha, beta = (next(s for s in spans(pdf) if s["text"] == word) for word in ("Alpha", "Beta"))
        distances.append(beta["origin"][1] - alpha["origin"][1])
    assert distances[1] - distances[0] == pytest.approx(5 * 72 / 25.4, abs=.01)


def test_fenced_code_and_following_paragraph_keep_grid_spacing():
    pdf = render("Before.\n\n```typst\n# Literal heading\n#list([Example])\n```\n\nAfter.")
    for s in spans(pdf):
        if s["text"] in ("NOTES", "1 of 1"):
            continue
        y = s["origin"][1] * 25.4 / 72 - 2.2
        assert y / 5 == pytest.approx(round(y / 5), abs=.002), s["text"]


@pytest.mark.parametrize("repeats", [8, 20])
def test_paragraph_with_inline_fractions_can_split_without_overlapping_next_paragraph(repeats):
    sentence = ('Reference flow uses $U=dot(m)/(rho A_("face"))$ and $C_v=A_1 L/D_a^2$. '
                'The coefficient is specific to the finished cloth. ')
    pdf = render('#v(195mm)\n\n'+sentence*repeats+'FIRSTEND.\n\nSECONDSTART. Following paragraph.', columns=2)
    words = [(i,w) for i,page in enumerate(pdf) for w in page.get_text("words")]
    end_page,end = next((i,w) for i,w in words if w[4] == "FIRSTEND.")
    next_page,start = next((i,w) for i,w in words if w[4] == "SECONDSTART.")
    assert end_page == next_page
    assert start[1] > end[3]  # The old fixed-height paragraph put both on the same line.
    assert start[1]-end[1] == pytest.approx(5*72/25.4, abs=.02)


def test_repeated_table_headers_do_not_compress_final_rows():
    source = '''from kip import *
# %% table "Long table"
Table(["Item", "Value"], [(f"ROW-{i:03d}", i) for i in range(100)])
'''
    pdf = pymupdf.open(stream=compile_pdf(emit(build(source=source))), filetype="pdf")
    assert len(pdf) >= 3
    rows = []
    for page in pdf:
        found = [s for b in page.get_text("dict")["blocks"] for line in b.get("lines", [])
                 for s in line["spans"] if s["text"].startswith("ROW-")]
        rows.extend(s["text"] for s in found)
        for a, b in zip(found, found[1:]):
            assert b["origin"][1] - a["origin"][1] >= 5 * 72 / 25.4 - .1
    assert rows == [f"ROW-{i:03d}" for i in range(100)]


def test_heading_only_cell_stays_with_its_following_drawing():
    source = '''from kip import *
# %% draw "First drawing"
Drawing(width=150, body="rect((0,0), (15,18))")
# %% text "Next section" section=1
# %% draw "Second drawing"
Drawing(width=150, body="rect((0,0), (15,12))")
'''
    pdf = pymupdf.open(stream=compile_pdf(emit(build(source=source))), filetype="pdf")
    assert len(pdf) == 2
    assert "Next section" not in pdf[0].get_text()
    assert "Next section" in pdf[1].get_text()
    assert "SECOND DRAWING" in pdf[1].get_text()


def test_raw_strings_preserve_literal_references_and_native_strings():
    source = r'''from kip import *
# %% text "Literal examples"
r"""
Escaped: \@val:escaped. Inline: `@val:inline` and `@src:inline`.

```typst
## Literal heading
@val:fenced @blk:fenced @req:fenced @src:fenced
```

#text("@val:native @src:native")
#let example = ("@val:first") + " @src:second"
#example
// @val:comment
/* @val:outer /* @src:inner */ */

#strong[Active: @val:P; see @blk:load.]
"""
# %% inputs load "Load"
P = 12 * kN
'''
    doc = build(source=source)
    assert not doc.warnings
    assert doc.graph.edges["literal_examples"] == frozenset({"__prelude__", "load"})
    pdf = pymupdf.open(stream=compile_pdf(emit(doc)), filetype="pdf")
    text = "".join(p.get_text() for p in pdf)
    for expected in ("@val:escaped", "@val:inline", "@src:inline", "## Literal heading",
                     "@val:fenced", "@src:fenced", "@val:native", "@src:native",
                     "@val:first", "@src:second", "Active: 12 kN; see Load."):
        assert expected in text
    assert "@val:comment" not in text and "@val:outer" not in text
    assert any(link["kind"] == pymupdf.LINK_GOTO for p in pdf for link in p.get_links())


def test_f_string_dependencies_are_resolved_before_prose_is_evaluated():
    doc = build(source='''from kip import *
# %% text "Result"
f"Computed {P.magnitude:.1f} kN; braces {{stay}}."
# %% inputs "Later input"
P = 12 * kN
''')
    assert doc.graph.order.index("later_input") < doc.graph.order.index("result")
    pdf = pymupdf.open(stream=compile_pdf(emit(doc)), filetype="pdf")
    assert "Computed 12.0 kN; braces {stay}." in "".join(p.get_text() for p in pdf)


def test_labels_and_substituted_values_render_as_literal_text():
    doc = build(source='''from kip import *
value = "#1 [a_b] @src:literal $x$"
# %% text "Introduction"
"""Value: @val:value; see @blk:details."""
# %% text details "Case #1 [a_b] @src:literal $x$" section=1
"""Plain labels."""
# %% plot "Plot"
plot([0*mm,1*mm], [0*MPa,1*MPa], xlabel="Axis [a_b]", ylabel=Math('sigma "(MPa)"'), label="Case #1")
''')
    pdf = pymupdf.open(stream=compile_pdf(emit(doc)), filetype="pdf")
    text = "".join(p.get_text() for p in pdf)
    assert "Value: #1 [a_b] @src:literal $x$;" in text
    assert text.count("Case #1 [a_b] @src:literal $x$") == 2
    assert "Axis [a_b]" in text and "Case #1" in text


@pytest.mark.parametrize("source", ['r"""unterminated', 'b"bytes"'])
def test_invalid_python_text_is_reported_against_its_cell(source):
    from kip.doc.kernel import ExecutionError

    with pytest.raises(ExecutionError, match=r"\[notes\]"):
        build(source='# %% text "Notes"\n' + source)
    assert build(source='# %% text "Notes"\n' + source, strict=False).results["notes"].failed


def test_rendering_specimen_keeps_all_rows_and_references():
    from pathlib import Path

    doc = build(Path(__file__).parent / "fixtures/rendering/doc.py")
    assert not doc.warnings
    pdf = pymupdf.open(stream=compile_pdf(emit(doc)), filetype="pdf")
    text = "".join(p.get_text() for p in pdf)
    for i in range(80):
        assert text.count(f"ROW-{i:03d}") == 1
    for word in ("@val:example", "@src:example", "Applied load", "Nested item", "Case #1"):
        assert word in text
