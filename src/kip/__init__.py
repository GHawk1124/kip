"""Public authoring API for Python engineering documents."""

from __future__ import annotations

__version__ = "0.1.0"

from .api import build_pdf
from .authoring import run_document, calculation, read_json, read_records
from .bio import Sequence, Structure, read_a3m, read_fasta, read_vcf, variant_table
from .chem import Molecule, molecule_grid, molecule_table, read_molecules
from .content import (
    Column, Drawing, Figure, Series, Source, Sources, Table, linspace, strip_units,
    Symbol, Math, nomenclature, inputs_table, plot,
)
from .sheets import Constant, Constants, Sheet
from .req import (
    ControlledVar, Item, Requirement, Requirements,
    compliance_matrix, flowdown_table, requirements_table, variables_table,
)
from .units import MATH_NAMES, UNIT_NAMES, Q, fmt_quantity, ureg

# Units and math functions are re-exported as bare names so a calc cell reads
# `2.5 * kN` and `sqrt(x)` exactly as they are rendered.
globals().update(UNIT_NAMES)
globals().update(MATH_NAMES)

__all__ = [
    "ureg", "Q", "fmt_quantity", "__version__",
    # rich content a block can bind
    "Figure", "Series", "Table", "Column", "Drawing", "Source", "Sources",
    "strip_units", "linspace",
    "Symbol", "Math", "nomenclature", "inputs_table", "plot",
    "build_pdf",
    "run_document", "calculation", "read_records", "read_json",
    # chemistry and biology
    "Molecule", "read_molecules", "molecule_table", "molecule_grid",
    "Sequence", "read_fasta", "read_a3m", "Structure", "read_vcf", "variant_table",
    # spreadsheet inputs
    "Constants", "Constant", "Sheet",
    # requirements and controlled variables
    "Requirements", "Requirement", "ControlledVar", "Item",
    "compliance_matrix", "requirements_table", "variables_table",
    "flowdown_table",
    *sorted(UNIT_NAMES), *sorted(MATH_NAMES),
]


def __getattr__(name: str):
    """Lazily expose heavier subsystems without importing them at startup."""
    if name in ("build", "execute", "Document", "Block"):
        from . import doc as _doc

        return getattr(_doc, name)
    if name in ("render", "emit", "Layout", "auto_layout"):
        from . import render as _render

        return getattr(_render, name)
    raise AttributeError(f"module 'kip' has no attribute {name!r}")
