"""Everything a document run found, once each, for people and for agents.

``kip check`` prints :func:`problems` and :func:`layout`; ``--json`` writes
them with :func:`blocks`, the values each cell computed, so an agent can
review a calculation without opening the PDF.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

__all__ = ["Problem", "problems", "layout", "blocks", "as_json"]

#: Internal kind names, as a marker spells them.
_KINDS = {"given": "inputs", "calculation": "calc"}


@dataclass
class Problem:
    severity: str        # "error" | "warning"
    message: str
    block: str = ""
    file: str = ""
    line: int | None = None
    hint: str = ""
    detail: str = ""     # the compiler's own text, when there is one

    def format(self) -> str:
        where = f"{self.file}:{self.line}" if self.line else self.file
        text = f"{where}: {self.severity}: " if where else f"{self.severity}: "
        text += (f"[{self.block}] " if self.block else "") + self.message
        if self.hint:
            text += f"\n    hint: {self.hint}"
        return text


def _location(text: str | None, fallback: Path) -> tuple[str, int | None]:
    if text and ":" in text:
        file, _, line = text.rpartition(":")
        if line.isdigit():
            return file, int(line)
    return str(fallback), None


def problems(document, doc_path: Path) -> list[Problem]:
    """Diagnostics, failed cells, failed checks and open verification, once each.

    A cell whose problem a diagnostic already names is not reported again for
    failing to run, and a name it could not find is not reported a third time.
    """
    from .doc.kernel import _all_requirements, where

    out = [Problem(d.severity, d.message, d.block_id, str(doc_path), d.line, d.hint)
           for d in document.diagnostics]
    reported = {d.block_id for d in document.errors}
    results = list(document.results.values())
    failed = {r.block_id for r in results if r.failed}
    for r in results:
        if r.failed and r.block_id not in reported:
            file, line = _location(where(r), doc_path)
            out.append(Problem("error", r.error or "failed", r.block_id, file, line))
    for bid, names in document.graph.unresolved.items():
        block = document.graph.by_id(bid)
        if names and block.kind != "text" and bid not in failed | reported:
            out.append(Problem("warning", "undefined: " + ", ".join(sorted(names)), bid,
                               str(doc_path), block.marker_line))
    for r in results:
        for check in r.assertions:
            if not check.passed:
                out.append(Problem("error", "check failed: " + check.describe(), r.block_id,
                                   check.file or str(doc_path), check.line))
    for reqs in _all_requirements(document.namespace):
        passed, failed_n, unverified = reqs.status()
        for c in reqs.checks:
            if not c.passed:
                out.append(Problem("error", f"{reqs.item.id}: {c.req_id} FAILED: "
                                            f"{c.value} {c.criterion}"))
        for rid in unverified:
            out.append(Problem("error", f"{reqs.item.id}: {rid} is not verified by this document"))
    for extension in document.extensions:
        for stage, (state, reason) in extension.outstanding.items():
            out.append(Problem("error", f"{stage}: {state} - {reason}"))
    return out


def layout(document, doc_path: Path, page_layout) -> tuple[list[Problem], list[str]]:
    """Compile the document once and read back how it was laid out.

    Returns the compile error, or equations drawn smaller than 85% of full
    size, as problems; and notes on pages left short because the next block
    did not fit. Nothing is written.
    """
    from .render import emit
    from .render.diagnostics import RenderError
    from .render.pdf import layout_markers

    try:
        marks = layout_markers(emit(document, page_layout))
    except (RenderError, ValueError, OSError) as exc:
        lines = str(exc).splitlines()
        hint = "; ".join(l.removeprefix("  hint: ") for l in lines if l.startswith("  hint: "))
        detail = getattr(exc, "diagnostic", "")
        locations = getattr(exc, "locations", [])
        if locations:
            file, block, line = locations[0]
            message = lines[0].split(f"[{block}] ", 1)[-1]
            return [Problem("error", message, block, file, line, hint, detail)], []
        return [Problem("error", lines[0], file=str(doc_path), hint=hint, detail=detail)], []

    starts = sorted((m for m in marks if "kind" in m and m.get("id") != "__end__"),
                    key=lambda m: (m["page"], m["y"]))
    ends = {m["id"]: m for m in marks if m.get("type") == "end"}

    def owner(page, y):
        found = None
        for m in starts:
            if (m["page"], m["y"]) <= (page, y + 0.01):
                found = m["id"]
        return found

    out: list[Problem] = []
    for m in marks:
        if m.get("type") != "shrunk":
            continue
        bid = owner(m["page"], m["y"])
        block = next((b for b in document.blocks if b.id == bid), None)
        number = f"equation ({m['number']})" if m.get("number") else "an equation"
        out.append(Problem(
            "warning", f"{number} is drawn at {m['scale']:.0%} of full size to fit "
                       f"page {m['page']}", bid or "", str(doc_path),
            block.marker_line if block else None,
            "split it into named intermediate results, or give the cell columns=1"))

    spec = page_layout.page
    g = spec.grid_step
    bottom = spec.size[1] - max(spec.snapped_margin(), 3 * g) - (spec.size[1] % g) / 2
    pages = max((m["page"] for m in starts), default=1)
    notes = []
    for page in range(1, pages):
        if any(m["page"] <= page < ends[m["id"]]["page"] for m in starts if m["id"] in ends):
            continue  # a cell carries on over the page break
        filled = max((e["y"] for e in ends.values() if e["page"] == page), default=None)
        following = next((m for m in starts if m["page"] == page + 1), None)
        if filled is None or following is None:
            continue
        block = next((b for b in document.blocks if b.id == following["id"]), None)
        if block is not None and block.meta.get("pagebreak", "false") in ("true", "before", "both"):
            continue
        if bottom - filled > spec.content_height / 3:
            end = ends.get(following["id"])
            tall = (f", {end['y'] - following['y']:.0f} mm tall,"
                    if end and end["page"] == following["page"] else "")
            notes.append(f"page {page} ends {bottom - filled:.0f} mm short: "
                         f"{following['id']}{tall} did not fit below it")
    return out, notes


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _value(value) -> dict:
    """A value as JSON: the number and its unit, and the text kip prints."""
    from .math.calc import unit_text
    from .units import fmt_quantity, plain_ratio, ureg

    if hasattr(type(value), "kip_summary"):
        return {"text": value.kip_summary()}  # a molecule, sequence, structure or alignment
    value = plain_ratio(value)
    if isinstance(value, ureg.Quantity):
        magnitude = value.magnitude
        if _number(magnitude) is not None:
            return {"value": magnitude, "unit": unit_text(value.units),
                    "text": fmt_quantity(value)}
        try:
            items = [float(x) for x in magnitude]
        except TypeError:
            return {"text": str(value)}
        return _series(items, unit_text(value.units))
    if isinstance(value, (bool, str)) or _number(value) is not None:
        return {"value": value, "text": fmt_quantity(value)}
    if isinstance(value, (list, tuple)) and value:
        if all(isinstance(v, ureg.Quantity) for v in value):
            unit = value[0].units
            try:
                return _series([v.to(unit).magnitude for v in value], unit_text(unit))
            except Exception:
                pass
        elif all(_number(v) is not None for v in value):
            return _series(list(value), "")
    return {"type": type(value).__name__}


def _series(items: list[float], unit: str) -> dict:
    from .units import fmt_number
    low, high = min(items), max(items)
    text = f"{len(items)} values, {fmt_number(float(low))} to {fmt_number(float(high))}"
    return {"count": len(items), "min": low, "max": high, "unit": unit,
            "text": f"{text} {unit}".strip()}


def blocks(document) -> list[dict]:
    """Each cell in document order: its state, values and checks."""
    from .authoring import Calculation
    from .math.calc import last_assigned_names

    out = []
    for block in document.ordered_blocks():
        result = document.results.get(block.id)
        entry = {"id": block.id, "kind": _KINDS.get(block.kind, block.kind),
                 "label": block.meta.get("label", ""), "line": block.marker_line,
                 "uses": sorted(d for d in document.graph.edges.get(block.id, ())
                                if d != "__prelude__")}
        if result is None:
            entry["state"] = "not run"
        elif result.failed:
            entry.update(state="failed", error=result.error or "")
        elif result.state != "PRESENT":
            entry.update(state=result.state.lower(), reason=result.reason)
        else:
            entry["state"] = "ok"
        values = {}
        order = {n: i for i, n in enumerate(last_assigned_names(block.source))}
        computed = (result.values if result else {}).items()
        for name, value in sorted(computed, key=lambda kv: order.get(kv[0], len(order))):
            if isinstance(value, Calculation):
                for inner, v in value.values.items():
                    shown = _value(v)
                    if not inner.startswith("_") and "type" not in shown:
                        values[f"{name}.{inner}"] = shown
            elif not callable(value) and "type" not in (shown := _value(value)):
                values[name] = shown
        if result is not None and result.calculation is not None and not values:
            values = {k: s for k, v in result.calculation.values.items()
                      if not k.startswith("_") and "type" not in (s := _value(v))}
        entry["values"] = values
        if result is not None and result.assertions:
            entry["checks"] = [{"line": c.line, "condition": c.condition, "passed": c.passed,
                                "message": c.message, "values": c.values}
                               for c in result.assertions]
        out.append(entry)
    return out


def as_json(document, doc_path: Path, found: list[Problem], notes: list[str]) -> dict:
    errors = sum(p.severity == "error" for p in found)
    return {"document": str(doc_path), "ok": not errors, "errors": errors,
            "warnings": sum(p.severity == "warning" for p in found),
            "problems": [asdict(p) for p in found], "notes": notes,
            "blocks": blocks(document)}
