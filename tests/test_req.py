"""Requirements, controlled variables and flow-down across documents."""
import pytest

from kip.doc import build
from kip.req import Requirements, RequirementsError, evaluate
from kip.req.matrix import compliance_matrix, variables_table
from kip.units import ureg

ASSEMBLY = '''
[item]
id = "SKID-4471"
name = "Process Skid"
kind = "assembly"
revision = "C"

[vars.P_design]
value = 18.0
unit = "kN"
description = "Design lift load"
source = "SKID-REQ-003"

[vars.DF_min]
value = 2.0

[req.SKID-REQ-003]
text = "Each lifting point shall carry P_design with factor DF_min."
verification = "analysis"
controls = ["P_design", "DF_min"]
'''

COMPONENT = '''
[item]
id = "LUG-001"
name = "Lift Lug"
kind = "component"
parent = "SKID-4471"
parent_file = "../skid/requirements.toml"
revision = "B"

[vars.sigma_y_min]
value = 250.0
unit = "MPa"

[req.REQ-014]
text = "The lug shall carry the design load with positive margin."
verification = "analysis"
parent = "SKID-REQ-003"
controls = ["P_design", "sigma_y_min"]
'''


@pytest.fixture
def tree(tmp_path):
    (tmp_path / "skid").mkdir()
    (tmp_path / "lug").mkdir()
    (tmp_path / "skid" / "requirements.toml").write_text(ASSEMBLY, encoding="utf-8")
    (tmp_path / "lug" / "requirements.toml").write_text(COMPONENT, encoding="utf-8")
    return Requirements.load(tmp_path / "lug" / "requirements.toml")


def test_controlled_variables_flow_down_from_the_parent(tree):
    """The whole point: a component reads the assembly's number, never copies it."""
    assert tree.P_design == 18.0 * ureg.kN
    assert tree.DF_min.magnitude == 2.0
    assert tree.sigma_y_min == 250.0 * ureg.MPa
    assert set(tree.all_variables()) == {"P_design", "DF_min", "sigma_y_min"}


def test_variable_provenance_is_recorded(tree):
    v = tree.var("P_design")
    assert v.owner == "SKID-4471"      # defined by the assembly
    assert v.source == "SKID-REQ-003"  # levied by that requirement


def test_lineage_is_root_first(tree):
    assert [i.id for i in tree.lineage()] == ["SKID-4471", "LUG-001"]
    assert [i.kind for i in tree.lineage()] == ["assembly", "component"]


def test_requirements_inherit_but_status_scopes_to_this_item(tree):
    assert set(tree.all_requirements()) == {"SKID-REQ-003", "REQ-014"}
    tree.verify("REQ-014", 1.13, ">= 0")
    passed, failed, unverified = tree.status()
    assert (passed, failed, unverified) == (1, 0, [])
    # a parent's requirement is discharged by the parent's own document
    assert tree.status(inherited=True)[2] == ["SKID-REQ-003"]


def test_criterion_may_reference_a_controlled_variable(tree):
    check = tree.verify("REQ-014", 260.0 * ureg.MPa, ">= sigma_y_min")
    assert check.passed
    assert not tree.verify("REQ-014", 240.0 * ureg.MPa, ">= sigma_y_min").passed


def test_criterion_checks_dimensions(tree):
    with pytest.raises(RequirementsError, match="cannot compare"):
        tree.verify("REQ-014", 5.0 * ureg.kg, ">= sigma_y_min")


@pytest.mark.parametrize("value,criterion,expected", [
    (1.5, ">= 1", True), (0.5, ">= 1", False),
    (5.0, "< 10", True), (5.0, "== 5", True),
    (200.0 * ureg.MPa, "<= 250 MPa", True),
    (300.0 * ureg.MPa, "<= 250 MPa", False),
])
def test_evaluate(value, criterion, expected):
    assert evaluate(value, criterion)[0] is expected


def test_bad_criterion_is_rejected():
    with pytest.raises(RequirementsError, match="must start with"):
        evaluate(1.0, "roughly 5")


def test_verifying_an_unknown_requirement_is_an_error(tree):
    with pytest.raises(RequirementsError, match="unknown requirement"):
        tree.verify("NOPE", 1, ">= 0")


def test_requirement_controlling_a_missing_variable_is_rejected(tmp_path):
    (tmp_path / "r.toml").write_text('''
[item]
id = "X"
[req.R1]
text = "t"
controls = ["nonexistent"]
''', encoding="utf-8")
    with pytest.raises(RequirementsError, match="not defined in"):
        Requirements.load(tmp_path / "r.toml")


def test_bad_verification_method_is_rejected(tmp_path):
    (tmp_path / "r.toml").write_text('''
[item]
id = "X"
[req.R1]
text = "t"
verification = "vibes"
''', encoding="utf-8")
    with pytest.raises(RequirementsError, match="not one of"):
        Requirements.load(tmp_path / "r.toml")


def test_circular_parent_chain_is_detected(tmp_path):
    for name, other in (("a", "b"), ("b", "a")):
        (tmp_path / f"{name}.toml").write_text(
            f'[item]\nid = "{name.upper()}"\nparent_file = "{other}.toml"\n',
            encoding="utf-8")
    with pytest.raises(RequirementsError, match="circular"):
        Requirements.load(tmp_path / "a.toml")


def test_compliance_matrix_marks_unverified_as_open(tree):
    rows, _ = compliance_matrix(tree).display_rows()
    assert rows[0][-1] == "OPEN"
    tree.verify("REQ-014", 1.0, ">= 0", evidence="margin")
    rows, _ = compliance_matrix(tree).display_rows()
    assert rows[0][-1] == "PASS" and rows[0][3] == "margin"


def test_variables_table_shows_where_each_value_comes_from(tree):
    rows, _ = variables_table(tree).display_rows()
    by_name = {r[0]: r for r in rows}
    assert by_name["P_design"][3] == "SKID-REQ-003"
    assert by_name["P_design"][4] == "SKID-4471"


# --- documents -------------------------------------------------------------

def test_document_resolves_requirements_relative_to_itself(tmp_path):
    """A build must not depend on the working directory it was run from."""
    (tmp_path / "skid").mkdir()
    proj = tmp_path / "lug"
    proj.mkdir()
    (tmp_path / "skid" / "requirements.toml").write_text(ASSEMBLY, encoding="utf-8")
    (proj / "requirements.toml").write_text(COMPONENT, encoding="utf-8")
    (proj / "doc.py").write_text('''from kip import *

# %% kip.requirements id=reqs
reqs = Requirements.load("requirements.toml")

# %% kip.controlled id=inputs label="Design load"
P = reqs.P_design

# %% kip.verify id=v
reqs.verify("REQ-014", 1.5, ">= 0", evidence="inputs")
''', encoding="utf-8")

    doc = build(path=proj / "doc.py")
    assert not doc.errors
    assert doc.value("P") == 18.0 * ureg.kN

    rows = doc.results["inputs"].controlled
    assert rows[0][0] == "P"
    assert rows[0][2].owner == "SKID-4471", "provenance survives into the render"

    assert doc.results["v"].checks[0].passed


def test_controlled_block_without_controlled_variables_fails_clearly():
    src = '''from kip import *

# %% kip.controlled id=inputs
x = 5 * mm
'''
    doc = build(source=src, path="doc.py", strict=False)
    assert doc.results["inputs"].failed
    assert "bound no controlled variables" in doc.results["inputs"].error


def test_controlled_blocks_are_not_linted_as_handcalcs():
    """Reading `reqs.P_design` is attribute access, which handcalcs mangles."""
    from kip.doc.loader import parse
    from kip.doc.validate import validate_all

    src = "from kip import *\n\n# %% kip.controlled id=c\nP = reqs.P_design\n"
    assert [d for d in validate_all(parse(src, "doc.py")) if d.severity == "error"] == []
