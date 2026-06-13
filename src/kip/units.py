"""Shared units and bare math names for handcalcs-compatible expressions."""

from __future__ import annotations

import math

import handcalcs
import pint

__all__ = ["ureg", "Q", "UNIT_NAMES", "MATH_NAMES", "namespace", "fmt_quantity"]

#: One registry for the whole process so quantities compose across blocks.
ureg = pint.UnitRegistry(autoconvert_offset_to_baseunit=True)
Q = ureg.Quantity

# handcalcs defaults to pint's *long* LaTeX format ("\mathrm{millimeter}").
# "~L" is the abbreviated form ("\mathrm{mm}").
handcalcs.set_option("preferred_string_formatter", "~L")
# One input per line; handcalcs' default of 3 columns runs values together when
# rendered through mitex.
handcalcs.set_option("param_columns", 1)

#: Units exported into every document namespace under their bare names.
_UNITS = """
    m cm mm um km inch ft yd mil
    kg g mg lb slug tonne
    s ms us minute hour day
    N kN MN lbf kip
    Pa kPa MPa GPa psi ksi bar
    J kJ MJ BTU
    W kW MW hp
    K degC degF degR
    rad deg rev
    Hz kHz MHz rpm
    A V ohm F H
    L mL gal
    mol
    dimensionless percent
"""

UNIT_NAMES: dict[str, object] = {}
for _name in _UNITS.split():
    try:
        UNIT_NAMES[_name] = getattr(ureg, _name)
    except AttributeError:  # pragma: no cover - registry drift
        pass

#: Math functions exported bare so handcalcs renders them as real operators.
MATH_NAMES: dict[str, object] = {
    "sqrt": math.sqrt,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "asin": math.asin,
    "acos": math.acos,
    "atan": math.atan,
    "atan2": math.atan2,
    "sinh": math.sinh,
    "cosh": math.cosh,
    "tanh": math.tanh,
    "exp": math.exp,
    "log": math.log,
    "log10": math.log10,
    "log2": math.log2,
    "pi": math.pi,
    "e": math.e,
    "floor": math.floor,
    "ceil": math.ceil,
    "abs": abs,
    "min": min,
    "max": max,
    "sum": sum,
}


def namespace() -> dict[str, object]:
    """A fresh document namespace pre-populated with units and math names."""
    ns: dict[str, object] = {}
    ns.update(UNIT_NAMES)
    ns.update(MATH_NAMES)
    ns["ureg"] = ureg
    ns["Q"] = Q
    return ns


def fmt_quantity(value: object, precision: int = 3) -> str:
    """Render a value for inline ``@val:`` substitution, units included."""
    if isinstance(value, ureg.Quantity):
        magnitude = value.magnitude
        unit = f"{value.units:~P}".strip()
        num = (f"{magnitude:.{precision}f}" if isinstance(magnitude, float)
               else f"{magnitude}")
        return f"{num} {unit}" if unit else num
    if isinstance(value, float):
        return f"{value:.{precision}f}"
    return str(value)
