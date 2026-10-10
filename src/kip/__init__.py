"""Public authoring API for Python engineering documents."""

from __future__ import annotations

__version__ = "0.1.0"

from .api import build_pdf
from .authoring import run_document, calculation, read_json, read_records
from .bio import Sequence, Structure, read_a3m, read_fasta, read_vcf, variant_table
from .chem import Molecule, molecule_grid, molecule_table, read_molecules
from .adapters import from_matplotlib
from .spice import Netlist, Signal, read_netlist, read_raw, simulate, spice_value, standard_value, E_SERIES
from .schematic import KicadNetlist, Schematic, from_schemdraw, from_skidl, read_schematic
from .pcb import (Board, read_bom, read_drill, read_gerber, read_gerbers, read_placement,
                  microstrip, stripline, trace_width)
from .hdl import (read_constraints, read_hdl, read_timing, read_utilization, read_vcd,
                  timing_diagram, wavedrom)
from .rf import polar_pattern, read_csx, read_touchstone, smith_chart
from .vlsi import read_gds, read_magic, read_metrics
from .measure import (average, bandwidth, crossover, cutoff, fall_time, fmax, gain_at, gain_margin,
                      overshoot, peak, peak_to_peak, period, phase_margin, pulse_width, resonance,
                      rise_time, rms, settling_time, value_at)
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
    # electronics: circuits, schematics, boards, digital, RF and chip layout
    "read_netlist", "Netlist", "simulate", "read_raw", "Signal", "spice_value", "standard_value", "E_SERIES",
    "Schematic", "read_schematic", "KicadNetlist", "from_skidl", "from_schemdraw", "from_matplotlib",
    "Board", "read_gerbers", "read_gerber", "read_drill", "read_bom", "read_placement",
    "trace_width", "microstrip", "stripline",
    "read_hdl", "read_vcd", "wavedrom", "timing_diagram", "read_utilization", "read_timing",
    "read_constraints",
    "read_touchstone", "smith_chart", "polar_pattern", "read_csx",
    "read_gds", "read_magic", "read_metrics",
    # measurements, as bare functions a calc cell renders
    "cutoff", "bandwidth", "gain_at", "crossover", "phase_margin", "gain_margin", "resonance",
    "rise_time", "fall_time", "overshoot", "settling_time", "period", "rms", "average", "peak",
    "peak_to_peak", "value_at", "pulse_width", "fmax",
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
