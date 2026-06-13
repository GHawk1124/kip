import pytest

from kip.doc.loader import KipSyntaxError, parse, replace_body

DOC = '''from kip import *

# %% kip.given id=loads label="Loads"
P = 2.5 * kN
L = 300 * mm

# %% kip.calc id=moment result_unit=kN*m
M = P * L

# %% kip.text id=notes
"""See @blk:moment."""
'''


def test_prelude_and_blocks():
    blocks = parse(DOC, "doc.py")
    assert [b.id for b in blocks] == ["__prelude__", "loads", "moment", "notes"]
    assert blocks[0].kind == "prelude"
    assert blocks[1].meta["label"] == "Loads"
    assert blocks[2].meta["result_unit"] == "kN*m"


def test_body_line_spans_are_accurate():
    lines = DOC.splitlines()
    for block in parse(DOC, "doc.py"):
        body = "\n".join(lines[block.body_start - 1: block.body_end])
        assert body.strip() == block.source.strip(), block.id


def test_replace_body_touches_nothing_else():
    """Block edits must preserve surrounding source."""
    blocks = parse(DOC, "doc.py")
    moment = next(b for b in blocks if b.id == "moment")
    out = replace_body(DOC, moment, "M = P * L * 2")

    assert "M = P * L * 2" in out
    # every other line survives byte-for-byte
    for line in ("P = 2.5 * kN", "L = 300 * mm", '"""See @blk:moment."""'):
        assert line in out
    # and the block structure is unchanged
    assert [b.id for b in parse(out, "doc.py")] == [b.id for b in blocks]


def test_round_trip_is_identity():
    blocks = parse(DOC, "doc.py")
    out = DOC
    for b in blocks:
        if b.kind != "prelude":
            out = replace_body(out, b, b.source)
    assert [x.id for x in parse(out, "doc.py")] == [x.id for x in blocks]


@pytest.mark.parametrize("bad,message", [
    ("# %% kip.calc\nx = 1", "missing 'id='"),
    ("# %% kip.bogus id=a\nx = 1", "unknown block kind"),
    ("# %% kip.calc id=a\nx=1\n# %% kip.calc id=a\ny=2", "duplicate block id"),
    ("# %% kip.calc id=9bad\nx = 1", "must be a valid identifier"),
])
def test_syntax_errors_are_reported_with_line_numbers(bad, message):
    with pytest.raises(KipSyntaxError) as exc:
        parse(bad, "doc.py")
    assert message in str(exc.value)
    assert "doc.py:" in str(exc.value)


def test_document_without_markers_is_all_prelude():
    blocks = parse("x = 1\ny = 2\n", "doc.py")
    assert len(blocks) == 1 and blocks[0].kind == "prelude"
