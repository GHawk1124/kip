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


def calculation(*, units=None, precision=3):
    """Render a function's equations and expose its computed local values.

    Set up inputs before ``# equations``; put straight-line arithmetic after it
    and end with ``return locals()``. The rendered arithmetic is validated by
    the same rules as inline calculation cells. Unit conversion happens after
    computation, just as for inline cells.
    """
    def decorate(fn):
        source = textwrap.dedent(inspect.getsource(fn))
        lines = source.splitlines()
        marker = next((i for i, line in enumerate(lines) if line.strip() == "# equations"), None)
        tree = ast.parse(source)
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef))
        if marker is None or not isinstance(function.body[-1], ast.Return):
            raise ValueError(f"{fn.__name__}: use # equations and return locals()")
        tail = function.body[-1].value
        if not (isinstance(tail, ast.Call) and isinstance(tail.func, ast.Name) and tail.func.id == "locals" and not tail.args and not tail.keywords):
            raise ValueError(f"{fn.__name__}: final statement must be return locals()")
        equations = textwrap.dedent("\n".join(lines[marker+1:function.body[-1].lineno-1]))
        from .doc.blocks import Block
        from .doc.validate import validate_all, ValidationError
        block = Block(id=fn.__name__, kind="calc", source=equations, marker_line=0, body_start=1, body_end=len(equations.splitlines()))
        errors = [d for d in validate_all([block], inspect.getsourcefile(fn)) if d.severity == "error"]
        if errors:
            raise ValidationError(errors, inspect.getsourcefile(fn))
        @wraps(fn)
        def wrapped(*args, **kwargs):
            values = fn(*args, **kwargs)
            for name, unit in (units or {}).items():
                values[name] = values[name].to(unit)
            return Calculation(equations, values, units or {}, precision)
        return wrapped
    return decorate
