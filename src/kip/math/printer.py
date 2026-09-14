"""SymPy -> Typst math printer.

There is no ``sympy.printing.typst`` upstream (only an open feature request), so
kip ships its own.  Symbolic blocks render through this printer directly, which
avoids a LaTeX round-trip; handcalcs output still goes via mitex.

Typst math notes that drive the implementation:

* A bare multi-letter word in math mode is a *symbol name*, not a product --
  ``sigma`` is the Greek letter, but ``max`` would be rendered as a symbol
  lookup too.  Literal text must be quoted: ``sigma_"max"``.
* ``a/b`` is a display fraction; ``a^b`` a superscript.  Multi-token
  sub/superscripts need parentheses: ``x^(n+1)``.
* Function application is ``f(x)``; named operators use ``op("name")``.
"""

from __future__ import annotations

import json
from sympy.printing.precedence import PRECEDENCE, precedence
from sympy.printing.printer import Printer

__all__ = ["TypstPrinter", "typst_math", "GREEK"]

#: Names Typst already knows as symbols and that must not be quoted.
GREEK = frozenset("""
    alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi
    omicron pi rho sigma tau upsilon phi chi psi omega
    Alpha Beta Gamma Delta Epsilon Zeta Eta Theta Iota Kappa Lambda Mu Nu Xi
    Omicron Pi Rho Sigma Tau Upsilon Phi Chi Psi Omega
    infinity infty ell
""".split())

#: sympy function name -> Typst built-in operator
_KNOWN_FUNCS = {
    "sin": "sin", "cos": "cos", "tan": "tan", "cot": "cot",
    "sec": "sec", "csc": "csc",
    "asin": "arcsin", "acos": "arccos", "atan": "arctan",
    "sinh": "sinh", "cosh": "cosh", "tanh": "tanh",
    "exp": "exp", "log": "ln", "ln": "ln",
    "Abs": "abs", "floor": "floor", "ceiling": "ceil",
    "Min": "min", "Max": "max",
}


def _split_name(name: str) -> tuple[str, str | None]:
    """Split ``sigma_max`` into ``("sigma", "max")``; ``x`` into ``("x", None)``."""
    if "_" not in name or name.startswith("_") or name.endswith("_"):
        return name, None
    base, _, sub = name.partition("_")
    return base, sub or None


def _atom(name: str) -> str:
    """Render one identifier fragment: a known symbol bare, anything else quoted."""
    if name in GREEK or (len(name) == 1 and name.isalpha()):
        return name
    if name.isdigit():
        return name
    return json.dumps(name, ensure_ascii=False)


def render_name(name: str) -> str:
    """``sigma_max`` -> ``sigma_"max"``; ``x`` -> ``x``; ``F_y`` -> ``F_y``."""
    base, sub = _split_name(name)
    out = "dot(m)" if base == "mdot" else _atom(base)
    if sub is not None:
        out += f"_{_atom(sub)}"
    return out


class TypstPrinter(Printer):
    """Print a SymPy expression as Typst math markup."""

    printmethod = "_typst"
    _default_settings: dict = {
        "order": None,
        "full_prec": "auto",
        "precision": 6,
        "mul_symbol": " dot ",
        "fold_short_frac": False,
    }

    # -- helpers ---------------------------------------------------------
    def parenthesize(self, item, level, strict=False) -> str:
        s = self._print(item)
        if precedence(item) < level or (strict and precedence(item) <= level):
            return f"({s})"
        return s

    def _group(self, s: str) -> str:
        """Wrap in parens unless already a single token."""
        if len(s) == 1 or (s.startswith("(") and s.endswith(")")):
            return s
        if s.startswith('"') and s.endswith('"') and '"' not in s[1:-1]:
            return s
        return f"({s})"

    # -- atoms -----------------------------------------------------------
    def _print_Symbol(self, expr) -> str:
        return render_name(expr.name)

    _print_Dummy = _print_Symbol

    def _print_Integer(self, expr) -> str:
        return str(expr.p)

    def _print_Float(self, expr) -> str:
        s = f"{float(expr):g}"
        if "e" in s:
            mant, _, exp = s.partition("e")
            return f"{mant} dot 10^({int(exp)})"
        return s

    def _print_Rational(self, expr) -> str:
        if expr.q == 1:
            return str(expr.p)
        return f"frac({expr.p}, {expr.q})"

    def _print_NaN(self, expr) -> str:
        return '"NaN"'

    def _print_Infinity(self, expr) -> str:
        return "infinity"

    def _print_NegativeInfinity(self, expr) -> str:
        return "-infinity"

    def _print_Exp1(self, expr) -> str:
        return "e"

    def _print_Pi(self, expr) -> str:
        return "pi"

    def _print_ImaginaryUnit(self, expr) -> str:
        return "i"

    def _print_BooleanTrue(self, expr) -> str:
        return '"true"'

    def _print_BooleanFalse(self, expr) -> str:
        return '"false"'

    # -- arithmetic ------------------------------------------------------
    def _print_Add(self, expr, order=None) -> str:
        terms = list(self._as_ordered_terms(expr, order=order))
        # Lead with a positive term where one exists: an engineer writes
        # "w - d", not "-d + w", and SymPy's canonical order often gives the
        # latter.
        if terms and terms[0].could_extract_minus_sign():
            for i, term in enumerate(terms):
                if not term.could_extract_minus_sign():
                    terms.insert(0, terms.pop(i))
                    break
        out = ""
        for i, term in enumerate(terms):
            s = self.parenthesize(term, PRECEDENCE["Add"])
            if i == 0:
                out = s
            elif s.startswith("-"):
                out += " - " + s[1:].lstrip()
            else:
                out += " + " + s
        return out

    def _print_Mul(self, expr) -> str:
        from sympy import Mul, Pow, S

        num, den = expr.as_numer_denom()
        if den is not S.One:
            return f"frac({self._print(num)}, {self._print(den)})"

        args = Mul.make_args(expr)
        sign = ""
        if args and args[0].is_Number and args[0].is_negative:
            if args[0] == -1:
                args = args[1:]
                sign = "-"
            else:
                args = (-args[0],) + args[1:]
                sign = "-"

        parts = [self.parenthesize(a, PRECEDENCE["Mul"]) for a in args]
        if not parts:
            return sign + "1"
        return sign + self._settings["mul_symbol"].join(parts)

    def _print_Pow(self, expr) -> str:
        from sympy import S

        base, exp = expr.base, expr.exp
        if exp == S.Half:
            return f"sqrt({self._print(base)})"
        if exp.is_Rational and exp.p == 1 and exp.q > 1:
            return f"root({exp.q}, {self._print(base)})"
        if exp.is_negative:
            from sympy import Pow

            inv = Pow(base, -exp)
            return f"frac(1, {self._print(inv)})"
        b = self.parenthesize(base, PRECEDENCE["Pow"], strict=True)
        e = self._print(exp)
        return f"{b}^{self._group(e)}"

    # -- relations -------------------------------------------------------
    _REL = {"==": "=", "!=": "!=", "<": "<", "<=": "<=", ">": ">", ">=": ">="}

    def _print_Relational(self, expr) -> str:
        op = self._REL.get(expr.rel_op, expr.rel_op)
        return f"{self._print(expr.lhs)} {op} {self._print(expr.rhs)}"

    def _print_Equality(self, expr) -> str:
        return f"{self._print(expr.lhs)} = {self._print(expr.rhs)}"

    # -- functions -------------------------------------------------------
    def _print_Function(self, expr, exp=None) -> str:
        name = expr.func.__name__
        args = ", ".join(self._print(a) for a in expr.args)
        if name in _KNOWN_FUNCS:
            return f"{_KNOWN_FUNCS[name]}({args})"
        return f'op("{name}")({args})'

    def _print_Abs(self, expr) -> str:
        return f"abs({self._print(expr.args[0])})"

    def _print_sqrt(self, expr) -> str:
        return f"sqrt({self._print(expr.args[0])})"

    def _print_exp(self, expr) -> str:
        arg = self._print(expr.args[0])
        # A fraction or long expression in a superscript renders microscopically;
        # fall back to the upright operator form.
        if "frac(" in arg or len(arg) > 12:
            return f"exp({arg})"
        return f"e^{self._group(arg)}"

    def _print_log(self, expr) -> str:
        if len(expr.args) == 2:
            return f"log_{self._group(self._print(expr.args[1]))}({self._print(expr.args[0])})"
        return f"ln({self._print(expr.args[0])})"

    # -- calculus --------------------------------------------------------
    def _print_Derivative(self, expr) -> str:
        total = sum(int(n) for _, n in expr.variable_count)
        top = "dif" if total == 1 else f"dif^{total}"
        bottom = " ".join(
            f"dif {self._print(v)}" if n == 1 else f"dif {self._print(v)}^{n}"
            for v, n in expr.variable_count
        )
        return f"frac({top} {self._print(expr.expr)}, {bottom})"

    def _print_Integral(self, expr) -> str:
        body = self._print(expr.function)
        out = ""
        for lim in expr.limits:
            if len(lim) == 3:
                out += (f"integral_{self._group(self._print(lim[1]))}"
                        f"^{self._group(self._print(lim[2]))} ")
            else:
                out += "integral "
        diffs = " ".join(f"dif {self._print(l[0])}" for l in expr.limits)
        return f"{out}{body} thin {diffs}"

    def _print_Sum(self, expr) -> str:
        lim = expr.limits[0]
        return (f"sum_({self._print(lim[0])}={self._print(lim[1])})"
                f"^{self._group(self._print(lim[2]))} {self._print(expr.function)}")

    def _print_Product(self, expr) -> str:
        lim = expr.limits[0]
        return (f"product_({self._print(lim[0])}={self._print(lim[1])})"
                f"^{self._group(self._print(lim[2]))} {self._print(expr.function)}")

    def _print_Limit(self, expr) -> str:
        e, z, z0 = expr.args[:3]
        return f"lim_({self._print(z)} arrow {self._print(z0)}) {self._print(e)}"

    # -- containers ------------------------------------------------------
    def _print_Piecewise(self, expr) -> str:
        rows = []
        for e, c in expr.args:
            if c is True or getattr(c, "is_Boolean", False) and bool(c) is True:
                rows.append(f'{self._print(e)} & "otherwise"')
            else:
                rows.append(f"{self._print(e)} & {self._print(c)}")
        return "cases(" + ", ".join(rows) + ")"

    def _print_MatrixBase(self, expr) -> str:
        rows = "; ".join(
            ", ".join(self._print(expr[i, j]) for j in range(expr.cols))
            for i in range(expr.rows)
        )
        return f"mat({rows})"

    _print_ImmutableDenseMatrix = _print_MatrixBase
    _print_MutableDenseMatrix = _print_MatrixBase
    _print_Matrix = _print_MatrixBase

    def _print_tuple(self, expr) -> str:
        return "(" + ", ".join(self._print(e) for e in expr) + ")"

    def _print_list(self, expr) -> str:
        return "(" + ", ".join(self._print(e) for e in expr) + ")"

    def emptyPrinter(self, expr) -> str:
        return f'"{expr}"'


def typst_math(expr, **settings) -> str:
    """Render a SymPy expression (or anything printable) as Typst math markup."""
    return TypstPrinter(settings).doprint(expr)
