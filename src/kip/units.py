"""Shared units and the bare math names calc cells render as operators."""

from __future__ import annotations

import math

import pint

__all__ = ["ureg", "Q", "UNIT_NAMES", "MATH_NAMES", "namespace", "fmt_quantity", "plain_ratio",
           "fmt_number", "significant", "unit_text", "FIGURES"]

#: Significant figures every computed value is shown to unless a cell says otherwise.
FIGURES = 4

#: One registry for the whole process so quantities compose across blocks.
ureg = pint.UnitRegistry(autoconvert_offset_to_baseunit=True)
Q = ureg.Quantity


def _mil_is_a_length(registry) -> None:
    """pint's ``mil`` is the angular (NATO) mil, 1/6400 of a turn; on a drawing a mil
    is a thousandth of an inch -- a track width, a coating. Make it that, and keep
    the angle as ``angular_mil``."""
    try:
        registry._units.pop("mil")
        registry.define("angular_mil = pi / 32000 * radian")
        registry.define("mil = 1e-3 * inch")
        registry._build_cache()
    except Exception:  # pragma: no cover - a pint without these internals
        pass


_mil_is_a_length(ureg)

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
    Hz kHz MHz GHz rpm
    A V ohm F H
    mA uA nA kA mV uV kV mW uW
    mohm kohm Mohm pF nF uF nH uH mH mS siemens
    ns ps
    L mL uL gal
    mol mmol umol nmol
    molar mM uM nM pM
    Da kDa
    nm angstrom
    ug ng kcal
    dimensionless percent
"""

UNIT_NAMES: dict[str, object] = {}
for _name in _UNITS.split():
    try:
        UNIT_NAMES[_name] = getattr(ureg, _name)
    except AttributeError:  # pragma: no cover - registry drift
        pass

def sqrt(x):
    """Square root that keeps units: sqrt(100 mm²) is 10 mm."""
    if isinstance(x, ureg.Quantity):
        return x ** 0.5
    return math.sqrt(x)


#: Math functions exported bare so calc cells render them as real operators.
MATH_NAMES: dict[str, object] = {
    "sqrt": sqrt,
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


def _trim(text: str) -> str:
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def significant(value: float, figures: int | None = None) -> tuple[str, int | None]:
    """``(digits, exponent)`` to ``figures`` significant figures.

    By default (``None``) that is :data:`FIGURES`, except that a short number
    -- 997.99, 0.4115, one that was typed or is exact -- is shown in full; only
    a long computed float is rounded. A whole-number part is never rounded
    away (83333.3 is ``83333``, not ``83330``). Below 0.0001 and from a
    million up, the value is ``digits × 10^exponent``. Trailing zeros are dropped.
    """
    if not value:
        return "0", None
    if figures is None:
        typed = len(repr(abs(value)).split("e")[0].replace(".", "").strip("0")) or 1
        figures = max(FIGURES, typed) if typed <= 5 else FIGURES
    e = math.floor(math.log10(abs(value)))
    if e >= 6 or e < -4:
        mantissa = f"{value / 10 ** e:.{figures - 1}f}"
        if abs(float(mantissa)) >= 10:  # 9.9996 rounded up to 10.000
            e += 1
            mantissa = f"{value / 10 ** e:.{figures - 1}f}"
        return _trim(mantissa), e
    return _trim(f"{value:.{max(0, figures - 1 - e)}f}"), None


_SUPERSCRIPT = str.maketrans("0123456789-.", "⁰¹²³⁴⁵⁶⁷⁸⁹⁻·")


def fmt_number(value: float, precision: int | None = None) -> str:
    """A number as an engineer writes it, to significant figures (:func:`significant`).

    A computed 12.16897 is ``12.17``, 0.0025 stays ``0.0025`` rather than
    rounding to ``0.003``, 83333.333 is ``83333``, and 4.16667e6 is
    ``4.167×10⁶`` -- not the ``4.17e6`` of a program's output.
    """
    if not isinstance(value, float):
        return str(value)
    if value != value or value in (float("inf"), float("-inf")):
        return str(value)
    digits, exponent = significant(value, precision)
    return digits if exponent is None else f"{digits}×10{str(exponent).translate(_SUPERSCRIPT)}"


def _unit_symbol(name: str) -> str:
    symbol = ureg.get_symbol(name)
    if symbol.endswith("l") and name.endswith("liter"):
        return symbol[:-1] + "L"  # mL and µL, as a laboratory writes them
    return {"deg": "°", "degree": "°"}.get(symbol, symbol)


def _power(symbol: str, exponent) -> str:
    if exponent == 1:
        return symbol
    text = f"{exponent:g}".translate(_SUPERSCRIPT)
    return symbol + text


def unit_text(units) -> str:
    """Compact, upright unit text: ``kg/m³``, ``kN·m``, ``W/(m²·K)``, ``°C``."""
    items = list(getattr(units, "_units", {}).items())
    num = [_power(_unit_symbol(n), e) for n, e in items if e > 0]
    den = [_power(_unit_symbol(n), -e) for n, e in items if e < 0]
    text = "·".join(num) or ("1" if den else "")
    if den:
        text += "/" + (den[0] if len(den) == 1 else "(" + "·".join(den) + ")")
    return text


def plain_ratio(value: object) -> object:
    """A dimensionless quantity as the number it is: MPa/ksi 10 reads 1.45.

    Units that are dimensionless in their own right -- degrees, radians,
    percent -- are kept; any other units that cancel are reduced, so a ratio
    of mixed units is not printed as ``10 MPa/ksi`` or ``3e-10 kN·m³/(GPa·mm⁵)``.
    """
    if not isinstance(value, ureg.Quantity) or not value.dimensionless:
        return value
    units = value._units
    kept = {u: p for u, p in units.items() if ureg.Quantity(1, u).dimensionless}
    if len(kept) == len(units):
        return value
    target = ureg.dimensionless
    for u, p in kept.items():
        target = target * ureg.Unit(u) ** p
    return value.to(target)


def fmt_quantity(value: object, precision: int | None = None) -> str:
    """Render a value for inline ``@val:`` substitution, units included.

    Units are written exactly as in a rendered calculation: ``kN·m``, ``30°``.
    """
    value = plain_ratio(value)
    if isinstance(value, ureg.Quantity):
        unit = unit_text(value.units)
        num = fmt_number(value.magnitude, precision)
        return f"{num}{'' if unit.startswith('°') else ' '}{unit}" if unit else num
    if isinstance(value, float):
        return fmt_number(value, precision)
    return str(value)
