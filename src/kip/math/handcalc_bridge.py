"""Render symbolic, substituted and evaluated calculations through handcalcs."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field

from handcalcs.handcalcs import LatexRenderer

from ..units import ureg

__all__ = ["RenderedCalc", "render_calc", "last_assigned_names", "MITEX_VERSION"]

#: Earlier versions 0.2.4/0.2.5 fail against Typst 0.15 ("unknown variable: kai").
MITEX_VERSION = "0.2.7"



@dataclass
class RenderedCalc:
    """Result of rendering one handcalcs block."""

    latex: str                    # body only; no $$ wrapper (wide form)
    latex_long: str = ""          # each step on its own line (narrow columns)
    assigned: list[str] = field(default_factory=list)
    converted: dict[str, str] = field(default_factory=dict)


class CalcRenderError(Exception):
    """handcalcs could not render this block."""


def last_assigned_names(source: str) -> list[str]:
    """Names assigned at the top level of ``source``, in order."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    names: list[str] = []
    for node in tree.body:
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        elif isinstance(node, ast.If):
            for sub in node.body + node.orelse:
                if isinstance(sub, ast.Assign):
                    targets.extend(sub.targets)
        for t in targets:
            if isinstance(t, ast.Name) and t.id not in names:
                names.append(t.id)
    return names


def _convert_result(
    namespace: dict, name: str, unit: str
) -> tuple[bool, str | None]:
    """Convert ``namespace[name]`` to ``unit`` in place. Returns (ok, error)."""
    value = namespace.get(name)
    if value is None:
        return False, f"block declares result_unit={unit} but defines no value"
    if not isinstance(value, ureg.Quantity):
        return False, (
            f"block declares result_unit={unit} but {name!r} is a plain "
            f"{type(value).__name__}, not a quantity with units"
        )
    try:
        namespace[name] = value.to(unit)
    except Exception as e:  # pint raises several types
        return False, (
            f"cannot convert {name!r} from {value.units:~P} to {unit}: {e}"
        )
    return True, None


def render_calc(
    source: str,
    namespace: dict,
    *,
    precision: int = 3,
    result_unit: str | None = None,
    result_units: list[tuple[str | None, str]] | None = None,
    override: str = "",
) -> RenderedCalc:
    """Render already-executed block ``source`` against ``namespace``.

    ``namespace`` must already contain the block's results (the kernel execs the
    block first).  If ``result_unit`` is given, the block's last assigned value
    is converted in the namespace *before* rendering, so the displayed result
    carries the requested unit.
    """
    assigned = last_assigned_names(source)
    converted: dict[str, str] = {}

    requests = list(result_units or [])
    if result_unit and not requests:
        requests = [(None, result_unit)]

    for name, unit in requests:
        target = name if name is not None else (assigned[-1] if assigned else None)
        if target is None:
            raise CalcRenderError(
                f"result_unit={unit} declared but the block assigns nothing"
            )
        if name is not None and target not in assigned:
            raise CalcRenderError(
                f"result_unit names {target!r}, which this block does not assign "
                f"(it assigns: {', '.join(assigned) or 'nothing'})"
            )
        ok, err = _convert_result(namespace, target, unit)
        if not ok:
            raise CalcRenderError(err or "unit conversion failed")
        converted[target] = unit

    def _render(mode: str) -> str:
        args = {"override": mode, "precision": precision, "sci_not": None}
        return _strip_wrapper(LatexRenderer(source, namespace, args).render())

    try:
        latex = _render(override)
        # handcalcs' "long" mode stacks symbolic / substituted / result on
        # separate lines. In a narrow column the default three-column form is
        # pushed far right and then shrunk by fit-width until it is unreadable,
        # so the emitter picks this form when the column is narrow.
        long = _tidy_long(_render("long")) if override in ("", "long") else latex
    except Exception as e:
        raise CalcRenderError(
            f"handcalcs could not render this block: {type(e).__name__}: {e}"
        ) from e

    return RenderedCalc(latex=latex, latex_long=long, assigned=assigned,
                        converted=converted)


def _tidy_long(latex: str) -> str:
    """Drop the trailing row separators handcalcs' long mode emits.

    They render as an empty final line, which pushes the result chip away from
    the equation it belongs to.
    """
    lines = latex.splitlines()
    # the closing \end{aligned} is last; strip blank rows and bare separators
    # immediately before it
    while len(lines) >= 2 and lines[-2].strip() in ("", "\\\\"):
        del lines[-2]
    if len(lines) >= 2:
        lines[-2] = lines[-2].rstrip().removesuffix("\\\\").rstrip()
    return "\n".join(lines)


def _strip_wrapper(latex: str) -> str:
    """Drop handcalcs' ``$$``/``\\[``  delimiters; mitex wants the body only."""
    s = latex.strip()
    for opener, closer in (("$$", "$$"), ("\\[", "\\]")):
        if s.startswith(opener):
            s = s[len(opener):]
            if s.rstrip().endswith(closer):
                s = s.rstrip()[: -len(closer)]
            break
    return s.strip()


def to_typst(rendered: RenderedCalc) -> str:
    """Wrap rendered LaTeX in a mitex call for the Typst emitter."""
    body = rendered.latex.replace("`", "\\`")
    return f"#mitex(`{body}`)"
