"""Render executed arithmetic as Typst math: symbolic, substituted, result.

A calc cell is ordinary Python restricted to what an engineer writes on a
calculation sheet: straight-line assignments, arithmetic, bare function calls
and ``if``/``elif``/``else``. Python runs it; this module then reads the same
syntax tree and prints each assignment three ways::

    sigma = P / A      ->   sigma = P/A = 2 kN / 100 mm² = 20 MPa

Rendering straight from the Python AST to Typst keeps the displayed algebra
identical to the code that produced the number. Anything outside that grammar
is rejected by :func:`check_calc` before execution, with a hint, rather than
rendered as something the code did not do.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from dataclasses import dataclass, field

import pint

from ..units import _power, fmt_quantity, plain_ratio, significant, unit_text, ureg
from .printer import render_name

__all__ = [
    "CalcRenderError", "Check", "Equation", "RenderedCalc", "render_calc", "check_calc",
    "last_assigned_names", "display_units", "unit_text", "value_math",
    "is_external_call", "convert", "with_conversions", "strip_checks", "has_checks",
    "dimension_name", "explain_dimensions",
]

#: ``sigma = M * c / I    # -> MPa`` asks for the result in MPa.
_ARROW_RE = re.compile(r"^#\s*->\s*(?P<unit>\S.*?)\s*$")


class CalcRenderError(Exception):
    """A calc cell could not be rendered as written.

    ``lineno`` is the line in the rendered source, when there is one; the
    kernel turns it into a ``file:line`` the author can open.
    """

    def __init__(self, message: str, lineno: int | None = None):
        super().__init__(message)
        self.lineno = lineno


@dataclass
class Equation:
    """One displayed line: ``lhs = parts[0] = parts[1] = ...``.

    A condition row (from ``if``) and a check row (from ``assert``) have an
    empty ``lhs`` and a single part.
    """

    lhs: str
    parts: list[str] = field(default_factory=list)
    kind: str = "equation"  # "equation" | "condition" | "check"

    def wide(self) -> str:
        if not self.lhs:
            return " = ".join(self.parts)
        return " = ".join([self.lhs, *self.parts])

    def stacked(self) -> list[str]:
        """Each step on its own row, for narrow columns.

        Continuation rows start with an invisible copy of the left-hand side,
        so left-aligned rows line up on their equals signs while each row
        still snaps to the page grid on its own.
        """
        if not self.lhs or len(self.parts) < 2:
            return [self.wide()]
        first, *rest = self.parts
        return [f"{self.lhs} = {first}", *(f"std.hide({self.lhs}) = {p}" for p in rest)]


@dataclass
class Check:
    """An ``assert`` in a calculation: the condition, its values, and the verdict."""

    line: int        # in the rendered source; the kernel makes it absolute
    condition: str   # as written: ``sigma <= sigma_allow``
    values: str      # the names it reads: ``sigma = 12.2 MPa, sigma_allow = 160 MPa``
    passed: bool
    message: str = ""
    file: str = ""

    def describe(self) -> str:
        what = f"{self.message}: " if self.message else ""
        return f"{what}{self.condition} is false ({self.values})"


@dataclass
class RenderedCalc:
    equations: list[Equation]
    assigned: list[str] = field(default_factory=list)
    converted: dict[str, str] = field(default_factory=dict)
    checks: list[Check] = field(default_factory=list)


# -- source helpers -------------------------------------------------------


def last_assigned_names(source: str) -> list[str]:
    """Names assigned at the top level of ``source`` (and in if-branches), in order."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    names: list[str] = []

    def visit(body):
        for node in body:
            targets: list[ast.expr] = []
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
            elif isinstance(node, ast.If):
                visit(node.body)
                visit(node.orelse)
            for t in targets:
                if isinstance(t, ast.Name) and t.id not in names:
                    names.append(t.id)

    visit(tree.body)
    return names


def display_units(source: str) -> "tuple[str, list[tuple[str, str]]]":
    """Split ``# -> unit`` annotations off the assignments they annotate.

    Returns the source with the annotations removed and the requested
    conversions, ``(name, unit)``, in source order.
    """
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
        tree = ast.parse(source)
    except (SyntaxError, tokenize.TokenError, IndentationError):
        return source, []

    assigned_at: dict[int, str] = {}
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)):
            assigned_at[node.end_lineno or node.lineno] = node.targets[0].id

    lines = source.splitlines()
    requests: list[tuple[str, str]] = []
    for token in tokens:
        if token.type != tokenize.COMMENT:
            continue
        match = _ARROW_RE.match(token.string.strip())
        if not match:
            continue
        row, col = token.start
        name = assigned_at.get(row)
        if name is None:
            raise CalcRenderError(
                f"'# -> {match.group('unit')}' must follow an "
                "assignment; it names the unit that result is displayed in", lineno=row)
        requests.append((name, match.group("unit")))
        lines[row - 1] = lines[row - 1][:col].rstrip()
    return "\n".join(lines), requests


def convert(value, unit: str, name: str):
    """``value.to(unit)`` with an error that names the result and the unit."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:  # a ratio asked for in percent: 0.057 is 5.7 %
            if ureg.Quantity(1, unit).dimensionless:
                return ureg.Quantity(value, "dimensionless").to(unit)
        except Exception:
            pass
    if not isinstance(value, ureg.Quantity):
        raise CalcRenderError(
            f"'# -> {unit}' asks for {name!r} in {unit}, but it is a plain "
            f"{type(value).__name__}, not a quantity with units")
    try:
        return value.to(unit)
    except pint.DimensionalityError as e:
        raise CalcRenderError(
            f"cannot convert {name!r} from {unit_text(value.units)} to {unit}: "
            f"{name} is {dimension_name(value)}, but {unit} is "
            f"{dimension_name(ureg.Quantity(1, unit))}") from e
    except Exception as e:  # an unknown unit name, chiefly
        raise CalcRenderError(f"cannot convert {name!r} to {unit}: {e}") from e


#: Dimensions an engineer names, keyed by a unit that has them.
_NAMED_DIMENSIONS = (
    ("dimensionless", "a plain number"), ("m", "a length"), ("m**2", "an area"),
    ("m**3", "a volume or section modulus"), ("m**4", "a second moment of area"),
    ("N", "a force"), ("Pa", "a pressure or stress"), ("N*m", "a moment or energy"),
    ("N/m", "a force per length"), ("kg", "a mass"), ("s", "a time"),
    ("kg/m**3", "a density"), ("m/s", "a velocity"), ("m/s**2", "an acceleration"),
    ("W", "a power"), ("K", "a temperature"), ("Hz", "a frequency"),
)


def dimension_name(value) -> str:
    """``a pressure or stress``; otherwise the dimensions: ``[force]/[length]³``."""
    dims = getattr(value, "dimensionality", ureg.dimensionless.dimensionality)
    for unit, name in _NAMED_DIMENSIONS:
        if ureg.Quantity(1, unit).dimensionality == dims:
            return name
    lengths = dict(dims / ureg.Quantity(1, "N").dimensionality)
    if set(lengths) == {"[length]"}:  # kN·m/mm⁴ reads better as force/length³
        k = lengths["[length]"]
        return f"[force]·{_power('[length]', k)}" if k > 0 else f"[force]/{_power('[length]', -k)}"
    items = list(dict(dims).items())
    num = [_power(n, e) for n, e in items if e > 0]
    den = [_power(n, -e) for n, e in items if e < 0]
    text = "·".join(num) or "1"
    if den:
        text += "/" + (den[0] if len(den) == 1 else "(" + "·".join(den) + ")")
    return text


def mixes_units(e: Exception) -> bool:
    """pint's two ways of saying both sides of an operation disagree in units."""
    return isinstance(e, pint.DimensionalityError) or (
        isinstance(e, ValueError) and str(e).startswith("Cannot compare"))


def explain_dimensions(node: ast.AST, namespace: dict) -> str | None:
    """Name the ``+``, ``-`` or comparison whose two sides disagree in dimension.

    pint says only "Cannot convert from 'megapascal' to 'dimensionless'";
    an author needs to know which terms of a long expression to look at.
    """
    def value(expr):
        return eval(compile(ast.Expression(expr), "<term>", "eval"), dict(namespace))

    for sub in ast.walk(node):
        if isinstance(sub, ast.BinOp) and isinstance(sub.op, (ast.Add, ast.Sub)):
            pairs = [(sub.left, sub.right, "add" if isinstance(sub.op, ast.Add) else "subtract")]
        elif isinstance(sub, ast.Compare):
            sides = [sub.left, *sub.comparators]
            pairs = [(a, b, "compare") for a, b in zip(sides, sides[1:])]
        else:
            continue
        for left, right, verb in pairs:
            try:
                lv, rv = value(left), value(right)
            except Exception:
                continue
            ld = getattr(lv, "dimensionality", ureg.dimensionless.dimensionality)
            rd = getattr(rv, "dimensionality", ureg.dimensionless.dimensionality)
            if ld != rd:
                a, b = ast.unparse(left), ast.unparse(right)
                if verb == "subtract":
                    a, b, lv, rv = b, a, rv, lv
                joiner = {"add": "and", "subtract": "from", "compare": "with"}[verb]
                return (f"cannot {verb} {a} ({dimension_name(lv)}) {joiner} "
                        f"{b} ({dimension_name(rv)})")
    return None


def with_conversions(body: list[ast.stmt], conversions: list[tuple[str, str]]) -> None:
    """Convert each annotated result right after the line that assigns it.

    ``sigma = M / Z  # -> MPa`` must hold MPa for the *next* line too, not
    only when it is displayed; otherwise a later ratio carries leftover
    units such as mm²·GPa/N. Works on a module body or a function body.
    """
    wanted = dict(conversions)

    def visit(stmts: list[ast.stmt]) -> None:
        i = 0
        while i < len(stmts):
            node = stmts[i]
            if isinstance(node, ast.If):
                visit(node.body)
                visit(node.orelse)
            elif (isinstance(node, ast.Assign) and len(node.targets) == 1
                  and isinstance(node.targets[0], ast.Name)
                  and node.targets[0].id in wanted):
                name = node.targets[0].id
                call = ast.parse(
                    f"{name} = __import__('kip.math.calc', fromlist=['convert'])"
                    f".convert({name}, {wanted[name]!r}, {name!r})").body[0]
                for part in ast.walk(call):  # errors in it point at the assignment
                    ast.copy_location(part, node)
                stmts.insert(i + 1, call)
                i += 1
            i += 1

    visit(body)
    for node in body:
        ast.fix_missing_locations(node)


def has_checks(stmts: list[ast.stmt]) -> bool:
    return any(isinstance(n, ast.Assert) for s in stmts for n in ast.walk(s))


def strip_checks(stmts: list[ast.stmt], after: int = 0) -> None:
    """Replace each ``assert`` (after line ``after``) with ``pass`` before running.

    A failed check is a result to report, not an exception: the cell keeps
    going, nothing downstream is blocked, and :func:`render_calc` evaluates
    and shows the condition from the finished namespace instead.
    """
    for i, node in enumerate(stmts):
        if isinstance(node, ast.Assert) and node.lineno > after:
            stmts[i] = ast.copy_location(ast.Pass(), node)
        elif isinstance(node, ast.If):
            strip_checks(node.body, after)
            strip_checks(node.orelse, after)


def is_external_call(tree: ast.Module) -> bool:
    """A cell that only calls a function from a module: ``analysis.size(C)``.

    That function is an ``@calculation``; it validates and renders its own
    equations, so the cell itself is not held to the arithmetic grammar.
    """
    if len(tree.body) != 1:
        return False
    node = tree.body[0]
    value = node.value if isinstance(node, (ast.Expr, ast.Assign)) else None
    if isinstance(node, ast.Assign) and not (
            len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)):
        return False
    return (isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute)
            and isinstance(value.func.value, ast.Name))


# -- grammar ---------------------------------------------------------------

_ARITH = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)
_HINT_SETUP = ("compute it before '# equations' in an @calculation, or in a "
               "prelude helper, and use the result by name")


def check_calc(tree: ast.Module, *, checks: bool = True) -> list[tuple[ast.AST, str, str]]:
    """Every construct the renderer cannot show faithfully: ``(node, message, hint)``.

    This is an allowlist. What is not listed below is refused, so nothing is
    rendered as algebra the code did not perform. ``checks=False`` refuses
    ``assert``, for cells that show values but not working.
    """
    problems: list[tuple[ast.AST, str, str]] = []

    def bad(node, message, hint=""):
        problems.append((node, message, hint))

    def expr(node, *, test=False):
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool):
                if not test:
                    bad(node, "True/False are not arithmetic", "use them only in an if test")
            elif not isinstance(node.value, (int, float)):
                bad(node, f"{type(node.value).__name__} values are not arithmetic", _HINT_SETUP)
        elif isinstance(node, ast.Name):
            pass
        elif isinstance(node, ast.Attribute):
            if not isinstance(node.value, ast.Name):
                bad(node, f"nested attribute access '.{node.attr}' is not rendered",
                    "bind the value to a name first")
        elif isinstance(node, ast.BinOp):
            if not isinstance(node.op, _ARITH):
                bad(node, f"operator {type(node.op).__name__} is not rendered",
                    "use + - * / ** only")
            expr(node.left, test=test)
            expr(node.right, test=test)
        elif isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.Not) and test:
                expr(node.operand, test=True)
            elif isinstance(node.op, (ast.USub, ast.UAdd)):
                expr(node.operand, test=test)
            else:
                bad(node, f"operator {type(node.op).__name__} is not rendered")
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "to":
                expr(func.value, test=test)
                if len(node.args) != 1 or node.keywords:
                    bad(node, ".to() takes exactly one unit")
            elif isinstance(func, ast.Attribute):
                bad(node, f"method call '.{func.attr}()' is not rendered",
                    "call bare function names such as sqrt(x); "
                    "import them in the prelude (from math import ...)")
            elif not isinstance(func, ast.Name):
                bad(node, "only named functions can be called")
            for arg in node.args:
                if isinstance(arg, ast.Starred):
                    bad(arg, "*args are not rendered")
                else:
                    expr(arg, test=test)
            for kw in node.keywords:
                if kw.arg is None:
                    bad(kw.value, "**kwargs are not rendered")
                else:
                    expr(kw.value, test=test)
        elif isinstance(node, (ast.Compare, ast.BoolOp)) and test:
            for sub in ([node.left, *node.comparators] if isinstance(node, ast.Compare)
                        else node.values):
                expr(sub, test=True)
        elif isinstance(node, ast.IfExp):
            bad(node, "conditional expressions (x if c else y) are not rendered",
                "use an if/else statement; the condition is then shown")
        elif isinstance(node, ast.Subscript):
            bad(node, "indexing is not rendered", _HINT_SETUP)
        else:
            bad(node, f"{type(node).__name__} is not arithmetic", _HINT_SETUP)

    def body(stmts, assigned: set[str], read: set[str]):
        for node in stmts:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if len(targets) != 1:
                    bad(node, "chained assignment (a = b = ...) is not rendered",
                        "use one assignment per line")
                    continue
                target = targets[0]
                if not isinstance(target, ast.Name):
                    bad(target, "assign to a single name; unpacking, attributes and "
                        "items are not rendered", "assign each name on its own line")
                    continue
                if node.value is None:
                    bad(node, "annotation without a value")
                    continue
                expr(node.value)
                names = {n.id for n in ast.walk(node.value) if isinstance(n, ast.Name)}
                read |= names
                if target.id in assigned or target.id in read:
                    bad(target, f"{target.id!r} is assigned again in this cell",
                        "give each result its own name; a substituted value "
                        "must mean one thing")
                assigned.add(target.id)
            elif isinstance(node, ast.If):
                expr(node.test, test=True)
                read |= {n.id for n in ast.walk(node.test) if isinstance(n, ast.Name)}
                a1, a2 = set(assigned), set(assigned)
                body(node.body, a1, read)
                body(node.orelse, a2, read)
                assigned |= a1 | a2
            elif isinstance(node, ast.Pass):
                pass
            elif isinstance(node, ast.Assert):
                if not checks:
                    bad(node, "a check (assert) is not shown in this cell",
                        "put checks in a calc cell, after the values they test")
                    continue
                expr(node.test, test=True)
                read |= {n.id for n in ast.walk(node.test) if isinstance(n, ast.Name)}
                if node.msg is not None and not (isinstance(node.msg, ast.Constant)
                                                 and isinstance(node.msg.value, str)):
                    bad(node.msg, "a check's message must be a plain string",
                        'assert sigma <= sigma_allow, "Bending stress"')
            elif isinstance(node, ast.AugAssign):
                bad(node, "augmented assignment (+=, *=, ...) is not rendered",
                    "write a new name: x_2 = x + 1")
            elif isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
                bad(node, "loops are not rendered", _HINT_SETUP)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                bad(node, "definitions are not rendered",
                    "define helpers in the prelude or analysis.py")
            elif isinstance(node, ast.Expr):
                bad(node, "a bare expression is not rendered",
                    "assign it to a name")
            else:
                bad(node, f"{type(node).__name__} statements are not rendered", _HINT_SETUP)

    body(tree.body, set(), set())
    return problems


# -- values ------------------------------------------------------------------

def _number_math(value, precision: int | None, *, exact: bool = False) -> str:
    """``exact`` keeps a written number exactly as typed."""
    if not isinstance(value, float) or value != value or value in (float("inf"), float("-inf")):
        return str(value)
    if exact:
        mantissa, _, exponent = repr(value).partition("e")
        return f"{mantissa} dot 10^({int(exponent)})" if exponent else mantissa
    digits, exponent = significant(value, precision)
    return digits if exponent is None else f"{digits} dot 10^({exponent})"


def _unit_math(units) -> str:
    text = unit_text(units)
    if not text:
        return ""
    joiner = "" if text.startswith("°") else "thin "
    return joiner + '"' + text.replace('"', '\\"') + '"'


def value_math(value, precision: int | None = None) -> tuple[str, int]:
    """A computed value as Typst math, with its binding strength."""
    value = plain_ratio(value)  # MPa/psi, mm/m: a plain ratio
    if isinstance(value, ureg.Quantity):
        number = _number_math(value.magnitude, precision)
        unit = _unit_math(value.units)
        text = f"{number} {unit}".strip()
        if number.startswith("-"):
            return text, _NEG
        return text, (_MUL if unit or "dot" in number else _ATOM)
    if isinstance(value, ureg.Unit):
        return _unit_math(value).removeprefix("thin "), _ATOM
    if isinstance(value, bool):
        return '"true"' if value else '"false"', _ATOM
    if isinstance(value, (int, float)):
        text = _number_math(value, precision)
        if text.startswith("-"):
            return text, _NEG
        return text, (_MUL if "dot" in text else _ATOM)
    if hasattr(type(value), "kip_summary") and "__str__" not in type(value).__dict__:
        value = value.kip_summary()  # a simulation, a report: say what it is
    return '"' + str(value).replace('"', '\\"') + '"', _ATOM


# -- printing ------------------------------------------------------------------

_ATOM, _POW, _UNARY, _MUL, _NEG, _ADD, _CMP, _NOT, _AND, _OR = 100, 80, 70, 60, 55, 50, 40, 35, 30, 20

_FUNCS = {
    "sqrt": "sqrt", "sin": "sin", "cos": "cos", "tan": "tan",
    "asin": "arcsin", "acos": "arccos", "atan": "arctan",
    "sinh": "sinh", "cosh": "cosh", "tanh": "tanh",
    "log": "ln", "log10": "log_10", "log2": "log_2",
    "min": "min", "max": "max", "abs": "abs", "floor": "floor", "ceil": "ceil",
}
_CMP_OPS = {ast.Gt: ">", ast.GtE: ">=", ast.Lt: "<", ast.LtE: "<=",
            ast.Eq: "=", ast.NotEq: "!="}


class _Printer:
    """Print one expression either symbolically or with values substituted."""

    def __init__(self, namespace: dict, *, substitute: bool, precision: int | None):
        self.ns = namespace
        self.substitute = substitute
        self.precision = precision

    def __call__(self, node) -> str:
        return self.print(node)[0]

    def wrap(self, node, level: int, *, strict: bool = False) -> str:
        text, prec = self.print(node)
        if prec < level or (strict and prec <= level):
            return f"({text})"
        return text

    def print(self, node) -> tuple[str, int]:
        method = getattr(self, "_" + type(node).__name__, None)
        if method is None:
            raise CalcRenderError(f"cannot render {type(node).__name__}")
        return method(node)

    def _Constant(self, node):
        return value_math(node.value, self.precision)

    def _name_value(self, name: str, value, symbol: str):
        if isinstance(value, ureg.Unit):
            return value_math(value)
        if name in ("pi", "e") and isinstance(value, float):
            return name, _ATOM
        if self.substitute and hasattr(type(value), "kip_summary"):
            return symbol, _ATOM  # a signal or a report has no value to write: it keeps its name
        if self.substitute:
            return value_math(value, self.precision)
        return symbol, _ATOM

    def _Name(self, node):
        return self._name_value(node.id, self.ns.get(node.id), render_name(node.id))

    def _Attribute(self, node):
        owner = self.ns.get(node.value.id) if isinstance(node.value, ast.Name) else None
        try:
            value = getattr(owner, node.attr)
        except Exception:  # displayed as a symbol even if unreadable
            value = None
        return self._name_value(node.attr, value, render_name(node.attr))

    def _UnaryOp(self, node):
        if isinstance(node.op, ast.USub):
            return "-" + self.wrap(node.operand, _UNARY), _NEG
        if isinstance(node.op, ast.UAdd):
            return self.print(node.operand)
        return "not " + self.wrap(node.operand, _NOT), _NOT

    def _literal(self, node) -> str | None:
        """``7850 * kg/m**3`` written as one quantity: ``7850 kg/m³``."""
        if not isinstance(node.op, (ast.Mult, ast.Div)) or not self._is_unit(node.right):
            return None
        head = node.left
        while isinstance(head, ast.BinOp) and isinstance(head.op, (ast.Mult, ast.Div)) \
                and self._is_unit(head.right):
            head = head.left
        if not self._is_number(head):
            return None
        try:
            value = eval(compile(ast.Expression(node), "<literal>", "eval"), dict(self.ns))
        except Exception:
            return None
        units = getattr(value, "units", None)
        if units is None:
            return None
        sign = "-" if isinstance(head, ast.UnaryOp) and isinstance(head.op, ast.USub) else ""
        written = head.operand.value if isinstance(head, ast.UnaryOp) else head.value
        # As written, not rounded to the display precision: it is an input.
        return f"{sign}{_number_math(written, None, exact=True)} {_unit_math(units)}".strip()

    def _BinOp(self, node):
        op = node.op
        literal = self._literal(node)
        if literal is not None:
            return literal, (_NEG if literal.startswith("-") else _MUL)
        if isinstance(op, ast.Div):
            return f"frac({self(node.left)}, {self(node.right)})", _ATOM
        if isinstance(op, ast.Pow):
            exponent = node.right
            if isinstance(exponent, ast.Constant) and exponent.value == 0.5:
                return f"sqrt({self(node.left)})", _ATOM
            base = self.wrap(node.left, _POW, strict=True)
            if base.startswith("frac(") or base.startswith("sqrt("):
                base = f"({base})"
            return f"{base}^({self(exponent)})", _POW
        if isinstance(op, ast.Mult):
            left, left_prec = self.print(node.left)
            negative = left_prec == _NEG  # -R T reads as -(R T): no brackets needed
            if not negative and left_prec < _MUL:
                left = f"({left})"
            right_text, right_prec = self.print(node.right)
            right = right_text if right_prec >= _MUL and not right_text.startswith("-") else f"({right_text})"
            return f"{left} dot {right}", (_NEG if negative else _MUL)
        left = self.wrap(node.left, _ADD)
        right_text, right_prec = self.print(node.right)
        if right_prec <= _ADD or right_text.startswith("-"):
            right_text = f"({right_text})"
        sign = "+" if isinstance(op, ast.Add) else "-"
        return f"{left} {sign} {right_text}", _ADD

    def _is_unit(self, node) -> bool:
        if isinstance(node, ast.Name):
            return isinstance(self.ns.get(node.id), ureg.Unit)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
            return self._is_unit(node.left) and self._is_number(node.right)
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Mult, ast.Div)):
            return self._is_unit(node.left) and self._is_unit(node.right)
        return False

    @staticmethod
    def _is_number(node) -> bool:
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            node = node.operand
        return isinstance(node, ast.Constant) and isinstance(node.value, (int, float))

    def _Call(self, node):
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "to":
            return self.print(func.value)  # the unit is carried by the result
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "f")
        args = [self(a) for a in node.args]
        args += [f'"{kw.arg}" = {self(kw.value)}' for kw in node.keywords]
        joined = ", ".join(args)
        if name == "exp":
            if len(joined) <= 14 and "frac(" not in joined:
                return f"e^({joined})", _POW
            return f"exp({joined})", _ATOM
        if name == "abs":
            return f"abs({joined})", _ATOM
        if name in _FUNCS:
            return f"{_FUNCS[name]}({joined})", _ATOM
        return f'op("{name}")({joined})', _ATOM

    def _Compare(self, node):
        parts = [self.wrap(node.left, _ADD)]
        for op, right in zip(node.ops, node.comparators):
            parts.append(_CMP_OPS.get(type(op), "?"))
            parts.append(self.wrap(right, _ADD))
        return " ".join(parts), _CMP

    def _BoolOp(self, node):
        word, level = (' "and" ', _AND) if isinstance(node.op, ast.And) else (' "or" ', _OR)
        return word.join(self.wrap(v, level + 1) for v in node.values), level


# -- rendering -----------------------------------------------------------------


def _convert(namespace: dict, name: str, unit: str) -> None:
    if namespace.get(name) is None:
        raise CalcRenderError(f"a display unit of {unit} was requested but {name!r} has no value")
    namespace[name] = convert(namespace[name], unit, name)


def _is_input(node, namespace) -> bool:
    """A bare number or quantity literal: nothing to substitute or evaluate."""
    printer = _Printer(namespace, substitute=False, precision=None)
    if printer._is_number(node):
        return True
    return isinstance(node, ast.BinOp) and printer._literal(node) is not None


def _dedupe(parts: list[str]) -> list[str]:
    out: list[str] = []
    for part in parts:
        if not out or out[-1] != part:
            out.append(part)
    return out


def render_calc(
    source: str,
    namespace: dict,
    *,
    precision: int | None = None,
    result_units: list[tuple[str | None, str]] | None = None,
) -> RenderedCalc:
    """Render already-executed ``source`` against ``namespace``.

    ``result_units`` converts named results (``None`` means the last one) in
    the namespace before rendering, so later cells and the display agree.
    """
    tree = ast.parse(source)
    problems = check_calc(tree)
    if problems:
        node, message, _ = problems[0]
        raise CalcRenderError(message, lineno=getattr(node, "lineno", 1))
    assigned = last_assigned_names(source)
    converted: dict[str, str] = {}
    for name, unit in result_units or []:
        target = name if name is not None else (assigned[-1] if assigned else None)
        if target is None:
            raise CalcRenderError(f"a result unit of {unit} was declared but the cell assigns nothing")
        if target not in assigned:
            raise CalcRenderError(
                f"a result unit names {target!r}, which this cell does not assign "
                f"(it assigns: {', '.join(assigned) or 'nothing'})")
        _convert(namespace, target, unit)
        converted[target] = unit

    symbolic = _Printer(namespace, substitute=False, precision=precision)
    substituted = _Printer(namespace, substitute=True, precision=precision)
    equations: list[Equation] = []
    checks: list[Check] = []

    def run(stmts):
        for node in stmts:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                target = node.targets[0] if isinstance(node, ast.Assign) else node.target
                result, _ = value_math(namespace.get(target.id), precision)
                written = symbolic(node.value)
                if _is_input(node.value, namespace):
                    parts = [written]  # an input reads as written, not rounded
                else:
                    parts = _dedupe([written, substituted(node.value), result])
                equations.append(Equation(render_name(target.id), parts))
            elif isinstance(node, ast.If):
                branch(node)
            elif isinstance(node, ast.Assert):
                check(node)

    def check(node: ast.Assert):
        try:
            passed = bool(eval(compile(ast.Expression(node.test), "<check>", "eval"), namespace))
        except Exception as e:
            why = mixes_units(e) and explain_dimensions(node.test, namespace)
            raise CalcRenderError(f"cannot evaluate the check: {why or f'{type(e).__name__}: {e}'}",
                                  lineno=node.lineno) from e
        message = node.msg.value if node.msg is not None else ""
        label = '"' + (message or "check").replace('"', '\\"') + '"'
        verdict = ('#text(fill: kip-colors.ok)[OK]' if passed
                   else '#text(fill: kip-colors.fail)[NOT OK]')
        row = (f"{label} quad {symbolic(node.test)} quad arrow.r.double quad "
               f"{substituted(node.test)} quad arrow.r.double quad {verdict}")
        equations.append(Equation("", [row], kind="check"))
        names = dict.fromkeys(n.id for n in ast.walk(node.test) if isinstance(n, ast.Name))
        values = ", ".join(f"{n} = {fmt_quantity(namespace[n])}" for n in names
                           if n in namespace and not isinstance(namespace[n], ureg.Unit))
        checks.append(Check(node.lineno, ast.unparse(node.test), values, passed, message))

    def branch(node: ast.If):
        try:
            taken = bool(eval(compile(ast.Expression(node.test), "<test>", "eval"), namespace))
        except Exception as e:
            why = mixes_units(e) and explain_dimensions(node.test, namespace)
            raise CalcRenderError(f"cannot evaluate the if test: {why or f'{type(e).__name__}: {e}'}",
                                  lineno=node.lineno) from e
        test = f'{symbolic(node.test)} quad arrow.r.double quad {substituted(node.test)}'
        verdict = '"true"' if taken else '"false"'
        equations.append(Equation("", [f'"if" quad {test} quad arrow.r.double quad {verdict}'],
                                  kind="condition"))
        if taken:
            run(node.body)
        elif len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If):
            branch(node.orelse[0])
        elif node.orelse:
            equations.append(Equation("", ['"else"'], kind="condition"))
            run(node.orelse)

    run(tree.body)
    return RenderedCalc(equations, assigned, converted, checks)
