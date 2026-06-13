import pytest

from kip.doc.graph import CycleError, analyze, analyze_code, analyze_text
from kip.doc.loader import parse


def test_execution_order_follows_dependencies_not_document_order():
    """The defining property: a block may be written before its inputs."""
    src = '''from kip import *

# %% kip.calc id=result
sigma = M * c / I

# %% kip.given id=inputs
M = 1 * kN * m
c = 25 * mm
I = 4e6 * mm**4
'''
    g = analyze(parse(src, "doc.py"))
    assert g.order.index("inputs") < g.order.index("result")


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


def test_cycle_is_a_hard_error_naming_the_blocks():
    src = '''from kip import *

# %% kip.calc id=a
x = y + 1

# %% kip.calc id=b
y = x + 1
'''
    with pytest.raises(CycleError) as exc:
        analyze(parse(src, "doc.py"))
    assert "a" in str(exc.value) and "b" in str(exc.value)


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
