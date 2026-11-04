"""Rich content a block can produce: figures, tables, drawings and sources.

A block binds one of these objects and the renderer picks it up, so authoring
stays ordinary Python::

    # %% kip.plot id=curve
    fig = Figure(xlabel="Deflection (mm)", ylabel="Load (kN)")
    fig.line(defl, load, label="Test", mark="o")

Everything here is *data*; nothing renders until the emitter walks it.  That
keeps the objects importable without Typst and testable without compiling.
"""

from __future__ import annotations

import numbers
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable, Sequence

from .units import fmt_number, fmt_quantity, plain_ratio, unit_text, ureg

__all__ = [
    "Figure", "Series", "Table", "Column", "Drawing", "Source", "Sources",
    "strip_units", "RichContent", "Symbol", "Math", "nomenclature", "inputs_table", "plot",
    "Listing",
]


def linspace(start, stop, num: int = 50):
    """``num`` evenly spaced values from ``start`` to ``stop``, units kept.

    ``x = linspace(0 * m, L, 41)`` is an array quantity, so a sweep reads as
    the formula it plots -- ``M = w * x * (L - x) / 2`` -- and ``plot(x, M)``
    labels both axes with their units. A plain ``0`` takes the other end's unit.
    """
    import numpy as np

    if isinstance(start, ureg.Quantity) or isinstance(stop, ureg.Quantity):
        unit = (stop if isinstance(stop, ureg.Quantity) else start).units
        ends = []
        for end in (start, stop):
            if isinstance(end, ureg.Quantity):
                ends.append(end.to(unit).magnitude)
            elif end == 0:
                ends.append(0.0)
            else:
                raise ValueError(f"linspace({start!r}, {stop!r}): give both ends units, "
                                 f"e.g. {end} * {unit:~P}")
        return ureg.Quantity(np.linspace(ends[0], ends[1], num), unit)
    return np.linspace(start, stop, num)


def strip_units(values: Iterable[Any], unit: str | None = None) -> list[float]:
    """Convert a sequence of quantities to plain floats for plotting.

    If ``unit`` is given every element is converted to it first, so a series
    mixing mm and m plots consistently rather than silently mis-scaling.
    """
    out: list[float] = []
    for v in values:
        if isinstance(v, ureg.Quantity):
            out.append(float(v.to(unit).magnitude if unit else v.magnitude))
        else:
            out.append(float(v))
    return out


def _infer_unit(values) -> str | None:
    if isinstance(values, ureg.Quantity):
        return None if values.dimensionless else f"{values.units:~P}"
    for v in values:
        if isinstance(v, ureg.Quantity):
            return f"{v.units:~P}"
    return None


def _magnitudes(values, unit: str | None) -> list[float]:
    """Plain floats for plotting, converted to ``unit``; a quantity array at once."""
    if isinstance(values, ureg.Quantity) and getattr(values.magnitude, "ndim", 0):
        values = values.to(unit) if unit else values
        return [float(v) for v in values.magnitude]
    return strip_units(list(values), unit)


def _series(x, y, label=None):
    """``(x, y, label)`` from ``plot(x, y)`` or from ``plot(signal)``: an object with a
    ``kip_series`` method gives its own axes."""
    if y is not None:
        return x, y, label
    if hasattr(type(x), "kip_series"):
        xs, ys, options = x.kip_series()
        return xs, ys, label if label is not None else options.get("label")
    raise TypeError("plot needs x and y, or one signal to plot")

# figures


@dataclass
class Series:
    """One plotted series."""

    x: list[float]
    y: list[float]
    label: str | Symbol | Math | None = None
    kind: str = "line"           # line | scatter | bar
    mark: str | None = None      # o, square, triangle, ...
    dash: str | None = None      # dashed, dotted, ...
    color: str | None = None


@dataclass
class Figure:
    """A 2-D plot rendered as vector graphics by lilaq.

    Axis labels pick up units automatically when the data are pint quantities,
    so ``fig.line(defl_mm, load_kn)`` is labelled ``Load (kN)`` without the
    author restating it.
    """

    xlabel: str | Symbol | Math | None = None
    ylabel: str | Symbol | Math | None = None
    title: str | Symbol | Math | None = None
    width: float = 120.0          # mm
    height: float = 70.0          # mm
    xscale: str = "linear"        # linear | log
    yscale: str = "linear"
    grid: bool = True
    legend: bool = True
    series: list[Series] = field(default_factory=list)
    xlim: tuple[float, float] | None = None
    ylim: tuple[float, float] | None = None
    #: The axes' units, set by the first series; later series are converted to them.
    xunit: str | None = field(default=None, repr=False)
    yunit: str | None = field(default=None, repr=False)

    def _add(self, kind, x, y, label, mark, dash, color, xunit, yunit) -> "Figure":
        x, y, label = _series(x, y, label)
        x = x if isinstance(x, ureg.Quantity) else list(x)
        y = y if isinstance(y, ureg.Quantity) else list(y)
        xu =xunit or self.xunit or _infer_unit(x)
        yu = yunit or self.yunit or _infer_unit(y)
        xs, ys = _magnitudes(x, xu), _magnitudes(y, yu)
        if len(xs) != len(ys):
            raise ValueError("plot x and y must have the same length")
        if isinstance(self.xlabel, str) and self.xlabel and xu and "(" not in self.xlabel:
            self.xlabel = f"{self.xlabel} ({xu})"
        if isinstance(self.ylabel, str) and self.ylabel and yu and "(" not in self.ylabel:
            self.ylabel = f"{self.ylabel} ({yu})"
        self.xunit, self.yunit = self.xunit or xu, self.yunit or yu
        self.series.append(Series(
            x=xs, y=ys, label=label, kind=kind, mark=mark, dash=dash, color=color,
        ))
        return self

    def line(self, x, y=None, label=None, mark=None, dash=None, color=None,
             xunit=None, yunit=None) -> "Figure":
        """Add a line: ``fig.line(x, y)``, or ``fig.line(signal)`` for a simulated signal."""
        return self._add("line", x, y, label, mark, dash, color, xunit, yunit)

    def scatter(self, x, y=None, label=None, mark="o", color=None,
                xunit=None, yunit=None) -> "Figure":
        return self._add("scatter", x, y, label, mark, None, color, xunit, yunit)

    def bar(self, x, y, label=None, color=None, xunit=None, yunit=None) -> "Figure":
        return self._add("bar", x, y, label, None, None, color, xunit, yunit)

    def of(self, expr, symbol, start, stop, n: int = 100, label=None, **kw) -> "Figure":
        """Plot a SymPy expression over a range -- verification by analysis."""
        import sympy as sp

        f = sp.lambdify(symbol, expr, "math")
        step = (stop - start) / max(1, n - 1)
        xs = [start + i * step for i in range(n)]
        ys = []
        for x in xs:
            try:
                ys.append(float(f(x)))
            except (ValueError, ZeroDivisionError, OverflowError):
                ys.append(float("nan"))
        return self.line(xs, ys, label=label or str(expr), **kw)

# tables


@dataclass(frozen=True)
class Symbol:
    """An engineering identifier with Greek letters and subscripts."""

    name: str

    def __str__(self) -> str:
        return self.name


@dataclass(frozen=True)
class Math:
    """Explicit inline Typst math, e.g. Math('sigma_y / 2')."""

    body: str

    def __str__(self) -> str:
        return self.body


@dataclass
class Column:
    key: str
    title: str | Symbol | Math | None = None
    unit: str | None = None       # convert quantities to this before display
    #: "left", "right" or "center"; None sets numbers right and words left.
    align: str | None = None
    #: Fixed decimal places; None shows significant figures, as calculations do.
    precision: int | None = None
    format: str | None = None     # e.g. "{:.1%}"
    math: bool = False            # identifier strings render as math symbols


def _alignment(values) -> str:
    """Numbers set right, so their digits line up; words and symbols set left;
    structure diagrams centre."""
    filled = [v for v in values if v is not None and not (isinstance(v, str) and v.strip() in ("", "-"))]
    if filled and all(hasattr(type(v), "kip_image") for v in filled):
        return "center"
    numeric = all(isinstance(v, (numbers.Number, ureg.Quantity)) and not isinstance(v, bool)
                  for v in filled)
    return "right" if filled and numeric else "left"


@dataclass
class Table:
    """Tabular data, rendered as a Typst table and optionally exported to xlsx.

    ``max_rows`` truncates the *rendered* table while the exported workbook
    keeps every row -- a 400-row sweep belongs in the spreadsheet, not in the
    middle of a design note.
    """

    columns: list[Column | str]
    rows: list[Sequence[Any]] = field(default_factory=list)
    title: str | None = None
    caption: str | None = None
    xlsx: str | None = None       # filename, written next to the PDF
    max_rows: int | None = None
    highlight: dict[int, str] = field(default_factory=dict)  # row -> "ok"|"fail"
    zebra: bool = True
    total_row: Sequence[Any] | None = None

    def __post_init__(self) -> None:
        self.columns = [
            c if isinstance(c, Column) else Column(key=str(c), title=str(c))
            for c in self.columns
        ]

        self.rows = list(self.rows)
        if not self.columns:
            raise ValueError("a table needs at least one column")
        for i, row in enumerate(self.rows):
            if len(row) != len(self.columns):
                raise ValueError(f"table row {i + 1}: expected {len(self.columns)} cells, got {len(row)}")
        self.columns = [c if c.align else replace(c, align=_alignment(row[i] for row in self.rows))
                        for i, c in enumerate(self.columns)]
        if self.total_row is not None and len(self.total_row) != len(self.columns):
            raise ValueError("table total row must match the column count")
        if self.max_rows is not None and self.max_rows < 0:
            raise ValueError("max_rows must be non-negative")

    @classmethod
    def from_records(cls, records, **options) -> "Table":
        """Dictionary keys become headers, preserving insertion order."""
        records = list(records)
        if not records:
            raise ValueError("from_records needs at least one record; use Table for an empty table")
        keys = list(records[0])
        if any(set(record) != set(keys) for record in records):
            raise ValueError("all table records must have the same keys")
        return cls(columns=keys, rows=[[record[k] for k in keys] for record in records], **options)

    @property
    def headers(self) -> list:
        out = []
        for c in self.columns:
            title = c.title or c.key
            out.append(f"{title} ({c.unit})" if c.unit and "(" not in str(title) else title)
        return out

    def cell_text(self, value: Any, col: Column) -> str:
        if value is None or hasattr(type(value), "kip_image"):
            return ""  # a structure diagram has no text to measure
        if isinstance(value, ureg.Quantity):
            if col.unit:
                value = value.to(col.unit).magnitude
                return fmt_number(float(value)) if col.precision is None else f"{value:.{col.precision}f}"
            if col.precision is None:
                return fmt_quantity(value)
            value = plain_ratio(value)
            unit = unit_text(value.units)
            return f"{value.magnitude:.{col.precision}f} {unit}".strip()
        if col.format:
            try:
                return col.format.format(value)
            except (ValueError, KeyError, IndexError):
                pass
        if isinstance(value, float):
            return fmt_number(value) if col.precision is None else f"{value:.{col.precision}f}"
        return str(value)

    def display_rows(self) -> tuple[list[list[str]], int]:
        """Formatted rows for the PDF, plus the count that was hidden."""
        shown = self.rows if self.max_rows is None else self.rows[: self.max_rows]
        hidden = len(self.rows) - len(shown)
        out = [
            [self.cell_text(v, c) for v, c in zip(row, self.columns)]
            for row in shown
        ]
        return out, hidden

    def raw_value(self, value: Any, col: Column) -> Any:
        """Native value for the spreadsheet: numbers stay numbers."""
        if hasattr(type(value), "kip_image"):
            return getattr(value, "smiles", str(value))
        if isinstance(value, ureg.Quantity):
            return float(value.to(col.unit).magnitude if col.unit
                         else value.magnitude)
        from sympy import Basic
        return str(value) if isinstance(value, (Symbol, Math, Basic)) else value

    def to_xlsx(self, path: str | Path) -> Path:
        """Write the full table (never truncated) as a real workbook."""
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter

        wb = Workbook()
        ws = wb.active
        ws.title = (self.title or "Data")[:31]

        head_fill = PatternFill("solid", fgColor="EDE6D3")
        head_font = Font(bold=True, color="1A1714")
        for j, header in enumerate(self.headers, start=1):
            cell = ws.cell(row=1, column=j, value=str(header))
            cell.fill = head_fill
            cell.font = head_font
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

        for i, row in enumerate(self.rows, start=2):
            for j, (value, col) in enumerate(zip(row, self.columns), start=1):
                cell = ws.cell(row=i, column=j, value=self.raw_value(value, col))
                cell.alignment = Alignment(horizontal=col.align, vertical="center")

        if self.total_row:
            r = len(self.rows) + 2
            for j, (value, col) in enumerate(zip(self.total_row, self.columns), start=1):
                cell = ws.cell(row=r, column=j, value=self.raw_value(value, col))
                cell.font = Font(bold=True)
                cell.alignment = Alignment(horizontal=col.align, vertical="center")

        for j, header in enumerate(self.headers, start=1):
            width = max(len(str(header)) + 2,
                        *(len(self.cell_text(row[j - 1], self.columns[j - 1])) + 2
                          for row in self.rows)) if self.rows else len(str(header)) + 2
            ws.column_dimensions[get_column_letter(j)].width = min(32, width)
        ws.freeze_panes = "A2"

        from .sheets import save_workbook
        return save_workbook(wb, path)

# drawings


@dataclass
class Drawing:
    """A vector drawing: CeTZ ``body`` or SVG bytes supplied by ``kip.cad``.

    ``width`` and ``height`` bound the displayed illustration. Attachments such
    as planar DXFs are exported beside the PDF and linked beneath the view.
    """

    body: str = ""
    width: float | None = None    # mm; None lets CeTZ size itself
    height: float | None = None
    caption: str | None = None
    length: str = "1cm"           # CeTZ unit length
    svg: bytes | None = None       # vector CAD projection, instead of CeTZ
    attachments: dict[str, bytes] = field(default_factory=dict)

    @classmethod
    def load(cls, path, *, width=170, height=None, caption=None):
        """Load SVG or wrap PNG bytes for the standard drawing renderer."""
        from .authoring import project_path
        import base64
        import struct
        path = project_path(path)
        data = path.read_bytes()
        if path.suffix.lower() == ".png":
            if data[:8] != b"\x89PNG\r\n\x1a\n":
                raise ValueError(f"invalid PNG: {path}")
            w, h = struct.unpack(">II", data[16:24])
            encoded = base64.b64encode(data).decode()
            data = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
                    f'<image width="{w}" height="{h}" href="data:image/png;base64,{encoded}"/></svg>').encode()
        elif path.suffix.lower() != ".svg":
            raise ValueError("Drawing.load supports SVG and PNG")
        return cls(svg=data, width=width, height=height, caption=caption)

    @classmethod
    def grid(cls, items, *, columns=2, width=170, height=None):
        """Compose (label, Drawing) pairs without changing their geometry."""
        import xml.etree.ElementTree as ET
        import math
        if not items or columns < 1:
            raise ValueError("drawing grid needs items and positive columns")
        ns = "http://www.w3.org/2000/svg"
        root = ET.Element(f"{{{ns}}}svg", viewBox=f"0 0 {400*columns} {370*math.ceil(len(items)/columns)}")
        for i, (label, drawing) in enumerate(items):
            x, y = (i % columns)*400, (i // columns)*370
            text = ET.SubElement(root, f"{{{ns}}}text", {"x":str(x+200), "y":str(y+18), "text-anchor":"middle", "font-family":"Arial", "font-size":"12"})
            text.text = label
            if drawing.svg is None:
                raise ValueError("Drawing.grid requires SVG or PNG drawings")
            child = ET.fromstring(drawing.svg)
            child.attrib.update(x=str(x), y=str(y+28), width="400", height="335", preserveAspectRatio="xMidYMid meet")
            # Avoid collisions between independently exported CAD SVG layers.
            ids = {e.attrib['id']: f"grid{i}_{e.attrib['id']}" for e in child.iter() if 'id' in e.attrib}
            for element in child.iter():
                for key, value in list(element.attrib.items()):
                    if key == 'id': element.set(key, ids[value])
                    else:
                        for old, new in ids.items():
                            value = value.replace(f'url(#{old})', f'url(#{new})')
                            if value == f'#{old}': value = f'#{new}'
                        element.set(key, value)
            root.append(child)
        return cls(svg=ET.tostring(root), width=width, height=height)

# sources


@dataclass
class Source:
    """A citable reference. Rendered as a clickable, formatted link."""

    title: str
    url: str | None = None
    author: str | None = None
    section: str | None = None
    year: int | str | None = None
    publisher: str | None = None
    note: str | None = None

    def short(self) -> str:
        """Compact in-line form, e.g. 'ASME B31.3 §302.3.5'."""
        bits = [self.title]
        if self.section:
            bits.append(self.section)
        return " ".join(bits)

    def full(self) -> str:
        """Reference-list form."""
        bits: list[str] = []
        if self.author:
            bits.append(self.author)
        bits.append(self.title)
        if self.publisher:
            bits.append(self.publisher)
        if self.year:
            bits.append(str(self.year))
        if self.section:
            bits.append(self.section)
        out = ", ".join(b for b in bits if b)
        if self.note:
            out += f" — {self.note}"
        return out


class Sources(dict):
    """Mapping of citation key -> :class:`Source`, cited with ``@src:key``."""

    def __init__(self, mapping: dict[str, Source | dict] | None = None, **kw):
        super().__init__()
        for k, v in {**(mapping or {}), **kw}.items():
            self[k] = v if isinstance(v, Source) else Source(**v)

    @classmethod
    def load(cls, *paths):
        """Merge reference workbooks, later ones winning, in one call.

        With no argument this reads ``input/references.xlsx``: one row per
        reference with ``key``, ``title``, ``author``, ``publisher``, ``year``,
        ``section``, ``url`` and ``note`` columns. An older ``sources.toml``
        of ``[sources.key]`` tables still loads (``kip migrate`` converts it).
        """
        import tomllib
        from .authoring import project_path
        from .doc.context import deprecated
        if not paths:
            defaults = ("input/references.xlsx", "sources.toml")
            paths = (next((p for p in defaults if project_path(p).exists()), defaults[0]),)
        merged: dict[str, Source] = {}
        for path in paths:
            resolved = project_path(path)
            if resolved.suffix.lower() in (".xlsx", ".xlsm"):
                from .sheets import Sheet
                merged.update(Sheet.load(resolved).sources())
                continue
            deprecated(f"{resolved.name} is an older form; references live in "
                       "input/references.xlsx (run kip migrate to convert it)")
            with resolved.open("rb") as stream:
                data = tomllib.load(stream)
            merged.update(cls(data.get("sources", {})))
        return cls(merged)


def nomenclature(entries=None, *sources, overrides=None, **options) -> Table:
    """A symbol table from document quantities, explicit sources, or a dictionary."""
    if not isinstance(entries, dict):
        from .quantities import generated_nomenclature
        return generated_nomenclature((entries, *sources) if entries is not None else sources,
                                      overrides, **options)
    if sources or overrides:
        raise ValueError("use a metadata source with overrides, or a standalone symbol dictionary")
    rows = []
    for name, entry in entries.items():
        description, unit = (entry, "-") if isinstance(entry, str) else entry
        rows.append((Symbol(name), description, unit))
    return Table([Column("symbol", "Symbol", align="left"),
                  Column("definition", "Definition", align="left"),
                  Column("unit", "Unit", align="left")], rows, **options)


def inputs_table(*sources, **options) -> Table:
    """Show captured calculation inputs, or all Constants/Requirements inputs."""
    from .quantities import inputs_table as generate
    return generate(*sources, **options)


def plot(x, y=None, *, label=None, mark=None, dash=None, color=None,
         xunit=None, yunit=None, **options) -> Figure:
    """Create a line plot in one call; chain .line(), .scatter() or .bar().

    ``plot(signal)`` plots a simulated signal against its sweep -- an AC
    response as a gain in dB on a logarithmic frequency axis -- with its axes
    labelled; options given here override those.
    """
    if y is None and hasattr(type(x), "kip_series"):
        _, _, defaults = x.kip_series()
        for key, value in defaults.items():
            if key != "label":
                options.setdefault(key, value)
    return Figure(**options).line(x, y, label=label, mark=mark, dash=dash,
                                 color=color, xunit=xunit, yunit=yunit)


@dataclass
class Listing:
    """A sequence set as a listing: numbered rows of letters in groups.

    :meth:`kip.bio.Sequence.listing` makes one; a draw cell renders it. Rows
    fill the column, so a narrow column has fewer groups per row. ``marks``
    maps 1-based positions to a key of ``legend``, which gives that key's
    colour and words: ``{"hotspot": ("#e69f00", "Interface hotspot")}``.
    """

    letters: str
    start: int = 1
    group: int = 10
    marks: dict[int, str] = field(default_factory=dict)
    legend: dict[str, tuple[str, str]] = field(default_factory=dict)
    caption: str | None = None

    def __post_init__(self) -> None:
        unknown = sorted(set(self.marks.values()) - set(self.legend))
        if unknown:
            raise ValueError(f"listing marks use {', '.join(unknown)}, which the legend does not define")
        outside = [p for p in self.marks if not self.start <= p < self.start + len(self.letters)]
        if outside:
            raise ValueError(f"listing marks position {outside[0]}, outside "
                             f"{self.start}-{self.start + len(self.letters) - 1}")


#: Types a block may bind for the renderer to pick up.
RichContent = (Figure, Table, Drawing, Sources, Listing)
