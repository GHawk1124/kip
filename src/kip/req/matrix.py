"""Render requirements, controlled variables and compliance as kip tables."""

from __future__ import annotations

from ..content import Column, Table, Math
from ..math.printer import render_name
from ..units import fmt_quantity
from .model import Requirements

__all__ = ["requirements_table", "variables_table", "compliance_matrix",
           "flowdown_table"]


def requirements_table(reqs: Requirements, *, inherited: bool = False,
                       xlsx: str | None = None) -> Table:
    """The requirement listing for this item (optionally including ancestors)."""
    source = reqs.all_requirements() if inherited else reqs.requirements
    rows = []
    for rid in sorted(source):
        r = source[rid]
        rows.append((
            rid, r.text, r.verification.title(),
            r.parent or "-",
            Math(", ".join(render_name(name) for name in r.controls)) if r.controls else "-",
        ))
    return Table(
        columns=[
            Column("id", "ID", align="left"),
            Column("text", "Requirement", align="left"),
            Column("method", "Method", align="left"),
            Column("parent", "Flows from", align="left"),
            Column("controls", "Controls", align="left"),
        ],
        rows=rows, xlsx=xlsx, zebra=True,
    )


def variables_table(reqs: Requirements, *, xlsx: str | None = None) -> Table:
    """Controlled variables visible to this item, with where each is defined."""
    rows = []
    for name, v in sorted(reqs.all_variables().items()):
        rows.append((
            name, fmt_quantity(v.quantity), v.description or "-",
            v.source or "-", v.owner,
        ))
    return Table(
        columns=[
            Column("name", "Variable", align="left", math=True),
            Column("value", "Value", align="right"),
            Column("desc", "Description", align="left"),
            Column("source", "Levied by", align="left"),
            Column("owner", "Defined in", align="left"),
        ],
        rows=rows, xlsx=xlsx, zebra=True,
    )


def compliance_matrix(reqs: Requirements, *, inherited: bool = False,
                      xlsx: str | None = None) -> Table:
    """One plain row per requirement; missing evidence remains OPEN."""
    source = reqs.all_requirements() if inherited else reqs.requirements
    by_req: dict[str, list] = {}
    for c in reqs.checks:
        by_req.setdefault(c.req_id, []).append(c)

    rows = []
    for rid in sorted(source):
        req = source[rid]
        checks = by_req.get(rid, [])
        if not checks:
            rows.append((rid, req.text, req.note or f"Awaiting {req.verification} evidence.", "OPEN"))
            continue
        evidence = []
        for check in checks:
            result = f"{fmt_quantity(check.value)} {check.criterion}"
            evidence.append(result + (f"; {check.evidence}" if check.evidence else ""))
        rows.append((rid, req.text, "\n".join(evidence), "PASS" if all(c.passed for c in checks) else "FAIL"))

    return Table(
        columns=[
            Column("id", "ID", align="left"),
            Column("text", "Requirement", align="left"),
            Column("evidence", "Assessment", align="left"),
            Column("status", "Status", align="left"),
        ],
        rows=rows, xlsx=xlsx, zebra=False,
    )


def flowdown_table(reqs: Requirements) -> Table:
    """The product-breakdown lineage, root item first."""
    rows = [
        (item.kind.title(), item.id, item.name or "-", item.revision or "-")
        for item in reqs.lineage()
    ]
    return Table(
        columns=[
            Column("kind", "Level", align="left"),
            Column("id", "Item", align="left"),
            Column("name", "Name", align="left"),
            Column("rev", "Rev", align="center"),
        ],
        rows=rows, zebra=True,
    )
