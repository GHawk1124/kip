"""Small conveniences shared by executable engineering documents."""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from functools import wraps
import inspect
from pathlib import Path
import textwrap


def project_path(path):
    from .req import model
    p = Path(path)
    return p if p.is_absolute() else (model._DOC_DIR or Path.cwd()) / p


def read_records(path, sheet="Inputs"):
    """Read a header-row Excel input table; reject formulas with stale caches."""
    from openpyxl import load_workbook
    path = project_path(path)
    book = load_workbook(path, read_only=True, data_only=False)
    try:
        values = iter(book[sheet].iter_rows(values_only=True))
        headers = next(values, ())
        if not headers or any(not isinstance(h, str) or not h for h in headers) or len(set(headers)) != len(headers):
            raise ValueError(f"{path}: expected unique, nonempty column headers")
        rows = []
        for row in values:
            if not any(v is not None for v in row):
                continue
            if any(isinstance(v, str) and v.startswith("=") for v in row):
                raise ValueError(f"{path}: input formulas are unsupported; enter values")
            rows.append(dict(zip(headers, (v if v is not None else "" for v in row))))
        return rows
    finally:
        book.close()


@dataclass
class Report:
    page: dict = field(default_factory=dict)
    output: str | None = None


def run_document(path, *, prepare=None, output=None, **page):
    """At script startup, build and exit; inside Kip, declare report settings.

    Put ``report = run_document(__file__, title="...", prepare=prepare)``
    before the first cell. ``prepare`` runs once, only for direct execution.
    CLI builds execute the document without invoking the preparation callback.
    """
    from .render.layout import PageSpec
    PageSpec(**page)  # Catch misspelled settings before doing preparation work.
    report = Report(page, output)
    if inspect.currentframe().f_back.f_globals.get("__name__") == "__main__":
        if prepare is not None:
            prepare()
        from .api import build_pdf
        print(build_pdf(path, output))
        raise SystemExit(0)
    return report


@dataclass
class Calculation:
    source: str
    values: dict
    units: dict
    precision: int = 3

    def __getattr__(self, key):
        try:
            return self.values[key]
        except KeyError as exc:
            raise AttributeError(key) from exc


def _equation_source(fn):
    """Split a decorated function into (setup, rendered equations, returns?).

    Everything after a ``# equations`` line is the arithmetic the document
    shows; anything before it is setup that only feeds it.  Without the marker
    the whole body is rendered.
    """
    source = textwrap.dedent(inspect.getsource(fn))
    lines = source.splitlines()
    tree = ast.parse(source)
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef))
    marker = next((i for i, line in enumerate(lines)
                   if line.strip() == "# equations"), None)

    returns = isinstance(function.body[-1], ast.Return)
    if returns:
        tail = function.body[-1].value
        if not (isinstance(tail, ast.Call) and isinstance(tail.func, ast.Name)
                and tail.func.id == "locals" and not tail.args and not tail.keywords):
            raise ValueError(
                f"{fn.__name__}: a calculation returns nothing, or returns locals()")
    start = marker + 1 if marker is not None else function.body[0].lineno - 1
    end = function.body[-1].lineno - 1 if returns else len(lines)
    return tree, function, textwrap.dedent("\n".join(lines[start:end])), returns


def calculation(fn=None, *, units=None, precision=3):
    """Render a function's equations and expose its computed local values.

    Set up inputs before ``# equations`` and write straight-line arithmetic
    after it; the rendered arithmetic is validated by the same rules as inline
    calculation cells.  Name the unit a result is read in beside the equation
    that produces it::

        @calculation
        def flow(c):
            rho_w = c.rho_w
            d_face = c.active_d
            # equations
            A_face = pi * d_face**2 / 4          # -> mm^2
            U_n = mdot_n / (rho_w * A_face)      # -> m/s
            return locals()

    ``return locals()`` is optional -- it is appended when absent.  ``units=``
    remains as an override for a unit that cannot be written as a comment.
    """
    def decorate(fn):
        from .math.handcalc_bridge import display_units
        tree, function, raw, returns = _equation_source(fn)
        equations, annotated = display_units(raw)
        conversions = annotated + list((units or {}).items())

        from .doc.blocks import Block
        from .doc.validate import validate_all, ValidationError
        path = inspect.getsourcefile(fn)
        block = Block(id=fn.__name__, kind="calc", source=equations, marker_line=0,
                      body_start=1, body_end=len(equations.splitlines()))
        errors = [d for d in validate_all([block], path) if d.severity == "error"]
        if errors:
            raise ValidationError(errors, path)

        inner = fn
        if not returns:
            # Rewriting the tail is what lets the author stop writing it.
            function.decorator_list = []
            function.body.append(ast.Return(ast.Call(
                func=ast.Name(id="locals", ctx=ast.Load()), args=[], keywords=[])))
            module = ast.fix_missing_locations(
                ast.Module(body=[function], type_ignores=[]))
            scope: dict = {}
            exec(compile(module, path or "<calculation>", "exec"),
                 fn.__globals__, scope)
            inner = scope[function.name]

        @wraps(fn)
        def wrapped(*args, **kwargs):
            values = inner(*args, **kwargs)
            for name, unit in conversions:
                if name not in values:
                    raise ValueError(
                        f"{fn.__name__}: '# -> {unit}' names {name!r}, "
                        "which this calculation does not assign")
                try:
                    values[name] = values[name].to(unit)
                except AttributeError as exc:
                    raise ValueError(
                        f"{fn.__name__}: {name!r} is a plain number, so it "
                        f"cannot be displayed in {unit}") from exc
            return Calculation(equations, values, dict(conversions), precision)
        return wrapped

    return decorate(fn) if fn is not None else decorate
