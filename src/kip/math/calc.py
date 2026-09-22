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

from ..units import fmt_number, ureg
from .printer import render_name

__all__ = [
    "CalcRenderError", "Equation", "RenderedCalc", "render_calc", "check_calc",
    "last_assigned_names", "display_units", "unit_text", "value_math",
    "is_external_call",
]

#: ``sigma = M * c / I    # -> MPa`` asks for the result in MPa.
_ARROW_RE = re.compile(r"^#\s*->\s*(?P<unit>\S.*?)\s*$")


class CalcRenderError(Exception):
    """A calc cell could not be rendered as written."""


@dataclass
class Equation:
    """One displayed line: ``lhs = parts[0] = parts[1] = ...``.

    A condition row (from ``if``) has an empty ``lhs`` and a single part.
    """

    lhs: str
    parts: list[str] = field(default_factory=list)

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
class RenderedCalc:
    equations: list[Equation]
    assigned: list[str] = field(default_factory=list)
    converted: dict[str, str] = field(default_factory=dict)


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
                f"line {row}: '# -> {match.group('unit')}' must follow an "
                "assignment; it names the unit that result is displayed in"
            )
        requests.append((name, match.group("unit")))
        lines[row - 1] = lines[row - 1][:col].rstrip()
    return "\n".join(lines), requests


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


def check_calc(tree: ast.Module) -> list[tuple[ast.AST, str, str]]:
    """Every construct the renderer cannot show faithfully: ``(node, message, hint)``.

    This is an allowlist. What is not listed below is refused, so nothing is
    rendered as algebra the code did not perform.
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

_SUPERSCRIPT = str.maketrans("0123456789-.", "⁰¹²³⁴⁵⁶⁷⁸⁹⁻·")


def _unit_symbol(name: str) -> str:
    symbol = ureg.get_symbol(name)
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


def _number_math(value, precision: int | None) -> str:
    """``precision=None`` keeps a written number exactly as typed."""
    if isinstance(value, float):
        text = repr(value) if precision is None else fmt_number(value, precision)
        text = text.replace("e+0", "e").replace("e-0", "e-").replace("e+", "e")
    else:
        text = str(value)
    if "e" in text:
        mantissa, _, exponent = text.partition("e")
        return f"{mantissa} dot 10^({int(exponent)})"
    return text


def _unit_math(units) -> str:
    text = unit_text(units)
    if not text:
        return ""
    joiner = "" if text.startswith("°") else "thin "
    return joiner + '"' + text.replace('"', '\\"') + '"'


def value_math(value, precision: int = 3) -> tuple[str, int]:
    """A computed value as Typst math, with its binding strength."""
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

    def __init__(self, namespace: dict, *, substitute: bool, precision: int):
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
        return f"{sign}{_number_math(written, None)} {_unit_math(units)}".strip()

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
            left = self.wrap(node.left, _MUL)
            right_text, right_prec = self.print(node.right)
            right = right_text if right_prec >= _MUL and not right_text.startswith("-") else f"({right_text})"
            return f"{left} dot {right}", _MUL
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
    value = namespace.get(name)
    if value is None:
        raise CalcRenderError(f"a display unit of {unit} was requested but {name!r} has no value")
    if not isinstance(value, ureg.Quantity):
        raise CalcRenderError(
            f"a display unit of {unit} was requested but {name!r} is a plain "
            f"{type(value).__name__}, not a quantity with units")
    try:
        namespace[name] = value.to(unit)
    except Exception as e:  # pint raises several types
        raise CalcRenderError(f"cannot convert {name!r} from {value.units:~P} to {unit}: {e}") from e


def _is_input(node, namespace) -> bool:
    """A bare number or quantity literal: nothing to substitute or evaluate."""
    printer = _Printer(namespace, substitute=False, precision=3)
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
    precision: int = 3,
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
        raise CalcRenderError(f"line {getattr(node, 'lineno', 1)}: {message}")
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

    def branch(node: ast.If):
        try:
            taken = bool(eval(compile(ast.Expression(node.test), "<test>", "eval"), namespace))
        except Exception as e:
            raise CalcRenderError(f"cannot evaluate the if test: {type(e).__name__}: {e}") from e
        test = f'{symbolic(node.test)} quad arrow.r.double quad {substituted(node.test)}'
        verdict = '"true"' if taken else '"false"'
        equations.append(Equation("", [f'"if" quad {test} quad arrow.r.double quad {verdict}']))
        if taken:
            run(node.body)
        elif len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If):
            branch(node.orelse[0])
        elif node.orelse:
            equations.append(Equation("", ['"else"']))
            run(node.orelse)

    run(tree.body)
    return RenderedCalc(equations, assigned, converted)
