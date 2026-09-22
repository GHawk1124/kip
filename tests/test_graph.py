import pytest

from kip.doc.graph import analyze, analyze_code, analyze_text
from kip.doc.loader import parse


def test_calculations_run_top_to_bottom_and_an_early_read_is_reported():
    src = '''from kip import *

# %% kip.calc id=result
sigma = M * c / I

# %% kip.given id=inputs
M = 1 * kN * m
c = 25 * mm
I = 4e6 * mm**4
'''
    g = analyze(parse(src, "doc.py"))
    assert g.order == ["__prelude__", "result", "inputs"]
    assert dict(g.early["result"]) == {"I": "inputs", "M": "inputs", "c": "inputs"}


def test_presentation_runs_after_every_calculation():
    src = '''from kip import *

# %% kip.table id=summary
Table.from_records([{"x": x}])

# %% kip.calc id=calc
x = 2 * mm

# %% kip.text id=note
"""x is @val:x"""
'''
    g = analyze(parse(src, "doc.py"))
    assert g.order == ["__prelude__", "calc", "summary", "note"]
    assert not g.early["summary"]
    assert "calc" in g.edges["summary"]


def test_a_read_inside_a_function_body_is_not_early():
    src = '''def later_value():
    return y

# %% kip.calc id=a
y = 2
'''
    g = analyze(parse(src, "doc.py"))
    assert not g.early["__prelude__"]


def test_a_later_redefinition_does_not_change_an_earlier_reader():
    src = '''from kip import *
# %% kip.given id=a
x = 1 * mm
# %% kip.calc id=b
y = x * 2
# %% kip.given id=c
x_new = 3 * mm
'''
    g = analyze(parse(src, "doc.py"))
    assert g.edges["b"] == frozenset({"__prelude__", "a"})


def test_edges_and_producers():
    src = '''from kip import *

# %% kip.given id=a
x = 1 * mm

# %% kip.calc id=b
y = x * 2
'''
    g = analyze(parse(src, "doc.py"))
    assert g.producers["x"] == "a"
    assert "a" in g.edges["b"]
    assert g.descendants("a") == {"b"}


def test_mutual_references_are_an_early_read_not_a_cycle():
    src = '''from kip import *

# %% kip.calc id=a
x = y + 1

# %% kip.calc id=b
y = x + 1
'''
    g = analyze(parse(src, "doc.py"))
    assert g.early["a"] == (("y", "b"),)
    assert "a" in g.edges["b"]


def test_unresolved_names_are_reported():
    src = '''from kip import *

# %% kip.calc id=a
y = undefined_thing * 2
'''
    g = analyze(parse(src, "doc.py"))
    assert "undefined_thing" in g.unresolved["a"]


def test_seeded_unit_names_are_not_unresolved():
    src = '''from kip import *

# %% kip.given id=a
P = 2.5 * kN
'''
    g = analyze(parse(src, "doc.py"))
    assert not g.unresolved["a"]


@pytest.mark.parametrize("code,defs,refs", [
    ("x = 1", {"x"}, set()),
    ("y = x + 1", {"y"}, {"x"}),
    ("total = sum(v**2 for v in data)", {"total"}, {"data"}),
    ("f = lambda q: q * scale", {"f"}, {"scale"}),
    ("out = [i * k for i in rng]", {"out"}, {"rng", "k"}),
    ("import numpy as np", {"np"}, set()),
    ("from math import sqrt", {"sqrt"}, set()),
    ("d = {k: v for k, v in pairs}", {"d"}, {"pairs"}),
])
def test_scope_analysis(code, defs, refs):
    """Comprehension and lambda locals must not leak into refs."""
    got_defs, got_refs = analyze_code(code)
    assert set(got_defs) == defs
    assert set(got_refs) == refs


def test_text_citations_create_dependencies():
    refs, cites = analyze_text("Value @val:sigma per @req:REQ-1, see @blk:calc1.")
    assert refs == {"sigma"}
    assert ("req", "REQ-1") in cites
    assert ("blk", "calc1") in cites


def test_text_block_depends_on_the_value_it_cites():
    src = '''from kip import *

# %% kip.text id=summary
"""Result is @val:sigma."""

# %% kip.calc id=calc
sigma = 2 * MPa
'''
    g = analyze(parse(src, "doc.py"))
    assert g.order.index("calc") < g.order.index("summary")
    assert "calc" in g.edges["summary"]
