"""Quantity metadata shared by calculations and their generated tables."""
from __future__ import annotations

import ast
from copy import deepcopy
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import replace
import io
from numbers import Real
import tokenize

from .content import Column, Symbol, Table
from .sheets import Constant, Constants
from .units import fmt_quantity, ureg


_READS = ContextVar("kip_quantity_reads", default=())


def scalar(value):
    magnitude = value.magnitude if isinstance(value, ureg.Quantity) else value
    return isinstance(magnitude, Real) and not isinstance(magnitude, bool)


def entry(name, value, **metadata):
    quantity = deepcopy(value) if isinstance(value, ureg.Quantity) else ureg.Quantity(value)
    return Constant(name, quantity, **metadata)


def controlled_entry(variable):
    return entry(variable.name, variable.quantity, description=variable.description,
                 source=variable.source or "", basis=variable.owner)


def record_read(owner, value: Constant):
    for reads in _READS.get():
        reads.append((id(owner), replace(value, quantity=deepcopy(value.quantity))))


@contextmanager
def collect_reads():
    reads = []
    token = _READS.set((*_READS.get(), reads))
    try:
        yield reads
    finally:
        _READS.reset(token)


def symbol_entries(source, values, reads=()):
    """Reuse metadata only for direct aliases; never infer it by equal values."""
    tree = ast.parse(source)
    read_map = {(owner, item.key): item for owner, item in reads}
    descriptions = {tok.start[0]: tok.string.lstrip("# ").strip()
                    for tok in tokenize.generate_tokens(io.StringIO(source).readline)
                    if tok.type == tokenize.COMMENT and not tok.string.lstrip("# ").startswith("->")}
    aliases = {}

    def origin(node):
        if isinstance(node, ast.Name):
            return aliases.get(node.id)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            return read_map.get((id(values.get(node.value.id)), node.attr))
        if (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name)
                and isinstance(node.slice, ast.Constant)):
            return read_map.get((id(values.get(node.value.id)), node.slice.value))
        return None

    container = tree.body[0] if len(tree.body) == 1 and isinstance(tree.body[0], ast.FunctionDef) else tree
    # Control-flow assignments can have several possible origins. Restrict
    # metadata inheritance to direct, unconditional aliases rather than guess.
    for node in container.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            for changed in ast.walk(node):
                if isinstance(changed, ast.Name) and isinstance(changed.ctx, ast.Store):
                    aliases.pop(changed.id, None)
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        pairs = [(target, node.value) for target in targets]
        if (len(targets) == 1 and isinstance(targets[0], (ast.Tuple, ast.List))
                and isinstance(node.value, (ast.Tuple, ast.List))):
            pairs = list(zip(targets[0].elts, node.value.elts))
        for target, value in pairs:
            if not isinstance(target, ast.Name):
                continue
            inherited = origin(value)
            if inherited is not None:
                aliases[target.id] = inherited
            else:
                aliases.pop(target.id, None)
            description = descriptions.get(node.end_lineno)
            if description and target.id in values and scalar(values[target.id]):
                base = aliases.get(target.id) or entry(target.id, values[target.id])
                aliases[target.id] = replace(base, description=description, description_inferred=False)

    names = sorted((n for n in ast.walk(tree) if isinstance(n, ast.Name)),
                   key=lambda n: (n.lineno, n.col_offset))
    out = {}
    for node in names:
        name = node.id
        if name.startswith("_") or name not in values or not scalar(values[name]):
            continue
        info = aliases.get(name)
        out[name] = (replace(info, key=name, symbol=name, quantity=entry(name, values[name]).quantity)
                     if info is not None else entry(name, values[name]))
    return out


def _source_entries(source, *, symbols=False):
    from .authoring import Calculation
    from .req import Requirements

    if isinstance(source, Constants):
        return [source.entry(key) for key in source]
    if isinstance(source, Requirements):
        return [controlled_entry(v) for v in source.all_variables().values()]
    if isinstance(source, Calculation):
        return list(source.symbols.values()) if symbols else source.input_entries
    raise TypeError("expected Constants, Requirements, or a @calculation result")


def inputs_table(*sources, **options):
    """Input values with their existing definitions, basis and provenance."""
    if not sources:
        raise ValueError("inputs_table needs a calculation, Constants, or Requirements")
    rows = []
    for source in sources:
        for item in _source_entries(source):
            row = (Symbol(item.symbol or item.key), fmt_quantity(item.quantity),
                   item.definition, item.source)
            if row not in rows:
                rows.append(row)
    columns = [Column("symbol", "Symbol", align="left"),
               Column("value", "Value / unit", align="left"),
               Column("definition", "Definition / basis", align="left")]
    if any(row[3] for row in rows):
        columns.append(Column("source", "Source", align="left"))
    else:
        rows = [row[:3] for row in rows]
    return Table(columns, rows, **options)


def symbol_table(entries, overrides=None, **options):
    chosen = {}
    for item in entries:
        name = item.symbol or item.key
        previous = chosen.get(name)
        if previous is not None:
            if previous.quantity.dimensionality != item.quantity.dimensionality:
                raise ValueError(f"nomenclature symbol {name!r} has incompatible units; select a narrower source")
            if previous.description and item.description and previous.description != item.description:
                if previous.description_inferred and not item.description_inferred:
                    chosen[name] = item
                    continue
                if item.description_inferred:
                    continue
                if not overrides or name not in overrides:
                    raise ValueError(f"nomenclature symbol {name!r} has conflicting descriptions; supply an override")
            if previous.description:
                continue
        chosen[name] = item
    overrides = overrides or {}
    unknown = set(overrides) - set(chosen)
    if unknown:
        raise ValueError("nomenclature overrides name unknown symbols: " + ", ".join(sorted(unknown)))
    rows = []
    for name, item in chosen.items():
        description = overrides.get(name, item.description)
        unit = f"{item.quantity.units:~P}" or "-"
        if isinstance(description, tuple):
            description, unit = description
            item.quantity.to(unit)  # reject a display unit with a different dimension
        rows.append((Symbol(name), description or "-", unit))
    return Table([Column("symbol", "Symbol", align="left"),
                  Column("definition", "Definition", align="left"),
                  Column("unit", "Unit", align="left")], rows, **options)


class AutoNomenclature(Table):
    """A table request resolved from document quantities after execution."""

    def __init__(self, overrides=None, **options):
        super().__init__(["Symbol", "Definition", "Unit"], **options)
        self.overrides = overrides
        self.options = options

    def resolve(self, entries):
        return symbol_table(entries, self.overrides, **self.options)


def generated_nomenclature(sources, overrides=None, **options):
    if not sources:
        return AutoNomenclature(overrides, **options)
    entries = [item for source in sources for item in _source_entries(source, symbols=True)]
    return symbol_table(entries, overrides, **options)
