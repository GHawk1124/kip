"""Spreadsheet inputs: constants with units, and sheets that render themselves.

An engineering document should *point at* its inputs, not restate them.  A
workbook already has a header row naming each column and a column declaring
each unit, so kip reads both rather than making the document repeat them::

    C = Constants.load("input/constants.xlsx")     # values carry units
    reqs = Sheet.load("input/requirements.xlsx", constants=C, unique="id")

``C.rho_w`` is a pint quantity, so a calculation writes ``rho = c.rho_w``
instead of ``c["rho_w"] * kg / m**3`` -- and a wrong unit in the workbook fails
where it is written rather than silently propagating a bare float.

``Sheet.table()`` turns the sheet straight into a document table, titled from
its own header row.  Cells may reference constants as ``{key}``; the value and
unit are substituted at load, so an unknown key is an error at the workbook
rather than a wrong number in the PDF.
"""

from __future__ import annotations

import datetime
import io
import re
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Iterator

from .content import Column, Source, Symbol, Table
from .units import fmt_quantity, ureg

__all__ = ["Constant", "Constants", "Sheet", "parse_unit", "save_workbook",
           "slug"]

_TEMPLATE_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)(?::(\d+))?\}")
#: ``kg/m3`` is how a unit is written in a spreadsheet; pint wants ``kg/m**3``.
_EXPONENT_RE = re.compile(r"(?<=[A-Za-z])(\d+)")


def slug(title: Any) -> str:
    """A stable identifier for a heading: ``ID / item`` -> ``id_item``."""
    out = re.sub(r"[^0-9a-zA-Z]+", "_", str(title)).strip("_").lower()
    if not out:
        raise ValueError(f"column heading {title!r} has no usable name")
    return out if not out[0].isdigit() else f"c_{out}"


#: A pinned date for generated workbooks. Any fixed value would do.
_FIXED_TIME = datetime.datetime(1980, 1, 1)

#: Document properties, emptied. openpyxl stamps the save time into the one it
#: writes, so the file is substituted rather than configured.
_BLANK_CORE = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<cp:coreProperties'
    ' xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"'
    ' xmlns:dc="http://purl.org/dc/elements/1.1/"'
    ' xmlns:dcterms="http://purl.org/dc/terms/"'
    ' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"/>'
).encode()

_BLANK_APP = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/'
    '2006/extended-properties"/>'
).encode()

_BLANK_PARTS = {"docProps/core.xml": _BLANK_CORE, "docProps/app.xml": _BLANK_APP}


def save_workbook(workbook, path: "str | Path") -> Path:
    """Write a workbook carrying no authorship, timestamps or tool identity.

    A generated input file should differ only when its data differs: whoever
    ran the script, when they ran it and what wrote it are not part of the
    design.  Those properties are emptied and every zip entry date is pinned,
    so rebuilding an unchanged workbook produces identical bytes.
    """
    workbook.properties.creator = ""
    workbook.properties.lastModifiedBy = ""
    workbook.properties.created = workbook.properties.modified = _FIXED_TIME

    buffer = io.BytesIO()
    workbook.save(buffer)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(buffer) as source, \
            zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as out:
        for name in sorted(source.namelist()):
            entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o600 << 16
            out.writestr(entry, _BLANK_PARTS.get(name) or source.read(name))
    return path


def parse_unit(text: Any) -> Any:
    """Parse a spreadsheet unit cell, accepting ``kg/m3`` for ``kg/m**3``."""
    text = "" if text is None else str(text).strip()
    if text in ("", "1", "-"):
        return ureg.dimensionless
    try:
        return ureg.Unit(text)
    except Exception:
        pass
    try:
        return ureg.Unit(_EXPONENT_RE.sub(r"**\1", text))
    except Exception as exc:
        raise ValueError(f"{text!r} is not a unit: {exc}") from exc

# constants


@dataclass(frozen=True)
class Constant:
    """One named input value, with the provenance that makes it reviewable."""

    key: str
    quantity: Any
    description: str = ""
    basis: str = ""
    source: str = ""
    symbol: str = ""
    description_inferred: bool = False

    def __str__(self) -> str:
        return fmt_quantity(self.quantity)

    @property
    def definition(self) -> str:
        return "; ".join(p for p in (self.description, self.basis) if p)


class Constants(Mapping):
    """Named quantities read from a workbook and extended programmatically.

    The standard sheet has a ``key`` and ``value`` column; ``unit``,
    ``description``, ``basis``, ``source`` and ``symbol`` are optional.  Every
    lookup returns a pint quantity, so downstream arithmetic is unit-checked::

        C = Constants.load("input/constants.xlsx")
        C.rho_w                      # 997.99 kg/m3
        C.add("rho_hot", CP.PropsSI(...) * kg / m**3, basis="CoolProp 6.6")
        C.override("temperature_F", 80 * degF, basis="hot-day case")
    """

    def __init__(self, entries: "dict[str, Constant] | None" = None):
        self._entries: dict[str, Constant] = dict(entries or {})

    # -- loading ---------------------------------------------------------
    @classmethod
    def load(cls, path: "str | Path" = "input/constants.xlsx", sheet: str = "Inputs") -> "Constants":
        raw = Sheet.load(path, sheet, unique="key")
        missing = {"key", "value"} - set(raw.keys)
        if missing:
            raise ValueError(
                f"{raw.path}: a constants sheet needs {', '.join(sorted(missing))} "
                f"column(s); found {', '.join(raw.keys)}"
            )
        entries: dict[str, Constant] = {}
        for i, row in enumerate(raw, start=2):
            key = str(row["key"]).strip()
            if not key.isidentifier():
                raise ValueError(f"{raw.path} row {i}: {key!r} is not a valid name")
            try:
                value = float(row["value"])
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"{raw.path} row {i}: {key} needs a numeric value") from exc
            if value != value or value in (float("inf"), float("-inf")):
                raise ValueError(f"{raw.path} row {i}: {key} is not finite")
            try:
                unit = parse_unit(row.get("unit"))
            except ValueError as exc:
                raise ValueError(f"{raw.path} row {i}: {key}: {exc}") from exc
            entries[key] = Constant(
                key=key, quantity=ureg.Quantity(value, unit),
                description=str(row.get("description", "") or ""),
                basis=str(row.get("basis", "") or ""),
                source=str(row.get("source", "") or row.get("source_url", "") or ""),
                symbol=str(row.get("symbol", "") or ""),
            )
        return cls(entries)

    # -- mapping ---------------------------------------------------------
    def __getitem__(self, key: str):
        try:
            item = self._entries[key]
        except KeyError:
            raise KeyError(
                f"no constant {key!r}; defined: {', '.join(sorted(self._entries))}"
            ) from None
        from .quantities import record_read
        record_read(self, item)
        return item.quantity

    def __iter__(self) -> Iterator[str]:
        return iter(self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(str(exc)) from None

    def value(self, key: str, unit=None) -> float:
        """The bare magnitude, for libraries that take plain numbers.

        A CAD kernel works in millimetres and knows nothing about pint, so it
        is handed ``C.value("body_d", mm)`` -- still a unit-checked conversion,
        just one that ends in a float.
        """
        quantity = self[key]
        return float(quantity.to(unit).magnitude if unit is not None
                     else quantity.magnitude)

    def entry(self, key: str) -> Constant:
        self[key]  # raise the same helpful KeyError
        return self._entries[key]

    # -- extension -------------------------------------------------------
    def add(self, key: str, value, unit=None, *, description: str = "",
            basis: str = "", source: str = "", symbol: str = "",
            override: bool = False) -> "Constants":
        """Define a constant computed in Python: a property lookup, fit or database.

        ``value`` may already be a quantity; otherwise pass ``unit``.  Adding a
        key the workbook already defines needs ``override=True`` so a generated
        value can never shadow a reviewed one by accident.
        """
        if key in self._entries and not override:
            raise ValueError(
                f"constant {key!r} is already defined; "
                "pass override=True to replace it")
        if not str(key).isidentifier():
            raise ValueError(f"{key!r} is not a valid constant name")
        if isinstance(value, ureg.Quantity):
            quantity = value.to(unit) if unit is not None else value
        else:
            quantity = ureg.Quantity(
                float(value),
                parse_unit(unit) if unit is not None else ureg.dimensionless)
        self._entries[key] = Constant(
            key=key, quantity=quantity, description=description, basis=basis,
            source=source, symbol=symbol)
        return self

    def override(self, key: str, value, unit=None, **kw) -> "Constants":
        """Replace a workbook value, keeping its description unless given."""
        previous = self.entry(key)
        kw.setdefault("description", previous.description)
        kw.setdefault("symbol", previous.symbol)
        return self.add(key, value, unit, override=True, **kw)

    # -- presentation ----------------------------------------------------
    def text(self, key: str, precision: int = 3) -> str:
        """The formatted value, for prose and for spreadsheet cell templates."""
        return fmt_quantity(self[key], precision)

    def format(self, template: str, precision: int = 3) -> str:
        """Substitute ``{key}`` (or ``{key:2}`` for precision) in a string."""
        def sub(m: "re.Match") -> str:
            digits = int(m.group(2)) if m.group(2) else precision
            return self.text(m.group(1), digits)
        return _TEMPLATE_RE.sub(sub, template)

    def table(self, *keys: str, title: str | None = None, **options) -> Table:
        """The constants as a document table: symbol, value, definition."""
        chosen = keys or tuple(self._entries)
        rows = []
        for key in chosen:
            entry = self.entry(key)
            rows.append((Symbol(entry.symbol or key), fmt_quantity(entry.quantity),
                         entry.definition))
        return Table(
            columns=[
                Column("symbol", "Symbol", math=True, align="left"),
                Column("value", "Value / unit", align="left"),
                Column("definition", "Definition / basis", align="left"),
            ],
            rows=rows, title=title, **options,
        )

    def sources(self) -> dict[str, Source]:
        """Citable sources for every constant that names one."""
        out: dict[str, Source] = {}
        for key, entry in self._entries.items():
            if entry.source:
                out[key] = Source(title=entry.description or key, url=entry.source,
                                  note=entry.basis)
        return out

# sheets


class Sheet(Sequence):
    """A workbook sheet: rows of values, and a header row that titles them.

    The header row is the display title; a snake_case key derived from it is
    how code addresses the column.  ``ID / item`` is therefore titled exactly
    that in the PDF and read as ``row["id_item"]``.
    """

    def __init__(self, records: "list[dict]", titles: "dict[str, Any]",
                 path: "Path | None" = None):
        self._records = records
        self.titles = dict(titles)
        self.path = path

    # -- loading ---------------------------------------------------------
    @classmethod
    def load(cls, path: "str | Path", sheet: str = "Inputs", *,
             constants: "Constants | None" = None,
             unique: "str | Sequence[str] | None" = None,
             required: "Sequence[str] | None" = None) -> "Sheet":
        """Read a sheet, interpolate ``{constant}`` cells, and check it.

        ``unique`` names column(s) whose values must not repeat and ``required``
        names column(s) that must be present and non-empty -- the checks every
        document was otherwise writing by hand.
        """
        from .authoring import project_path, read_records

        resolved = project_path(path)
        raw = read_records(resolved, sheet)
        if not raw:
            raise ValueError(f"{resolved}: sheet {sheet!r} has no rows")
        titles = {slug(t): t for t in raw[0]}
        if len(titles) != len(raw[0]):
            raise ValueError(f"{resolved}: column headings collide once slugified")

        records = []
        for i, row in enumerate(raw, start=2):
            record = {}
            for title, value in row.items():
                if isinstance(value, str) and constants is not None:
                    unknown = [m.group(1) for m in _TEMPLATE_RE.finditer(value)
                               if m.group(1) not in constants]
                    if unknown:
                        raise ValueError(
                            f"{resolved} row {i}: unknown constant(s) "
                            + ", ".join(unknown))
                    value = constants.format(value)
                record[slug(title)] = value
            records.append(record)

        obj = cls(records, titles, resolved)
        for key in ([unique] if isinstance(unique, str) else list(unique or ())):
            obj.require_unique(key)
        for key in (required or ()):
            obj.require_present(key)
        return obj

    # -- sequence --------------------------------------------------------
    def __len__(self) -> int:
        return len(self._records)

    def __getitem__(self, index):
        if isinstance(index, str):
            return [r.get(index) for r in self._records]
        return self._records[index]

    @property
    def keys(self) -> "list[str]":
        return list(self.titles)

    # -- checks ----------------------------------------------------------
    def _check_column(self, key: str) -> None:
        if key not in self.titles:
            raise ValueError(
                f"{self.path}: no column {key!r}; found {', '.join(self.titles)}")

    def require_unique(self, key: str) -> "Sheet":
        self._check_column(key)
        seen: set = set()
        for i, row in enumerate(self._records, start=2):
            value = row.get(key)
            if value in seen:
                raise ValueError(f"{self.path} row {i}: duplicate {key} {value!r}")
            seen.add(value)
        return self

    def require_present(self, key: str) -> "Sheet":
        self._check_column(key)
        for i, row in enumerate(self._records, start=2):
            if row.get(key) in (None, ""):
                raise ValueError(f"{self.path} row {i}: {key} is empty")
        return self

    # -- output ----------------------------------------------------------
    def table(self, *keys: str, hide: "Sequence[str]" = (), titles=None,
              align: str = "left", **options) -> Table:
        """Render the sheet as a document table, titled from its header row."""
        chosen = list(keys) or [k for k in self.titles if k not in set(hide)]
        for key in chosen:
            self._check_column(key)
        overrides = dict(titles or {})
        columns = [Column(k, overrides.get(k, self.titles[k]), align=align)
                   for k in chosen]
        rows = [[row.get(k) for k in chosen] for row in self._records]
        return Table(columns=columns, rows=rows, **options)

    def sources(self, key: str = "key", **columns: str) -> "dict[str, Source]":
        """Citable sources keyed by a column, for ``@src:`` citations.

        Every :class:`~kip.content.Source` field reads the column of the same
        name, so a references workbook with ``title``, ``author``,
        ``publisher``, ``year``, ``section``, ``url`` and ``note`` columns needs
        no mapping at all.  A sheet that calls them something else says so:
        ``sheet.sources(title="supplier_item", note="catalog_basis")``.
        """
        self.require_unique(key)
        mapping = {f.name: columns.get(f.name, f.name) for f in fields(Source)}
        for column in columns.values():
            self._check_column(column)

        out: "dict[str, Source]" = {}
        for row in self._records:
            values = {}
            for field, column in mapping.items():
                cell = row.get(column)
                values[field] = str(cell) if cell not in (None, "") else None
            values["title"] = values["title"] or ""
            out[str(row[key])] = Source(**values)
        return out

    def records(self) -> "list[dict]":
        """A copy of the rows, keyed by column name."""
        return [dict(r) for r in self._records]
