"""Execute dependency-ordered blocks and cache their results."""

from __future__ import annotations

import traceback
from dataclasses import dataclass, field, replace
from pathlib import Path

from ..math.calc import CalcRenderError, render_calc
from ..math.printer import typst_math
from ..units import fmt_quantity, namespace as fresh_namespace
from .blocks import Block
from .graph import DependencyGraph, analyze
from .loader import parse
from .validate import Diagnostic, validate_all

__all__ = ["BlockResult", "Document", "ExecutionError", "run"]


@dataclass
class BlockResult:
    """Everything the renderer needs about one executed block."""

    block_id: str
    kind: str
    ok: bool = True
    equations: list = field(default_factory=list)  # rendered calc lines (math.calc.Equation)
    typst: str | None = None          # native Typst math (symbolic blocks)
    text: str | None = None           # resolved prose
    content: object | None = None     # Figure / Table / Drawing / Sources
    calculation: object | None = None  # decorated result, including a bare call
    quantities: dict = field(default_factory=dict)
    derived: object | None = None
    checks: list = field(default_factory=list)   # verification results
    #: (name, value, controlled-variable) triples for a kip.controlled block
    controlled: list = field(default_factory=list)
    values: dict[str, object] = field(default_factory=dict)
    error: str | None = None
    traceback: str | None = None
    cache_key: str = ""
    state: str = "PRESENT"
    reason: str = ""

    @property
    def failed(self) -> bool:
        return not self.ok


class ExecutionError(Exception):
    """A block raised during execution and the document cannot be rendered."""

    def __init__(self, results: list[BlockResult], path: str | Path = "doc.py"):
        self.results = results
        failures = [r for r in results if r.failed]
        super().__init__(
            f"{len(failures)} block(s) failed in {path}:\n"
            + "\n".join(f"  [{r.block_id}] {r.error}" for r in failures)
        )


@dataclass
class Document:
    """A parsed, analysed and (optionally) executed kip document."""

    path: Path
    source: str
    blocks: list[Block]
    graph: DependencyGraph
    diagnostics: list[Diagnostic] = field(default_factory=list)
    results: dict[str, BlockResult] = field(default_factory=dict)
    namespace: dict = field(default_factory=dict)
    #: block id -> relative path of a side-car file written for it (xlsx, ...)
    assets: dict[str, str] = field(default_factory=dict)
    packet: object | None = None

    @property
    def errors(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == "error"]

    @property
    def warnings(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == "warning"]

    def ordered_blocks(self) -> list[Block]:
        """Blocks in *document* order (the order they are rendered in)."""
        return [b for b in self.blocks if b.kind != "prelude"]

    def value(self, name: str):
        return self.namespace.get(name)


def _cache_key(block: Block, graph: DependencyGraph, keys: dict[str, str]) -> str:
    """Hash of this block plus everything it transitively depends on."""
    import hashlib

    h = hashlib.blake2b(digest_size=16)
    h.update(block.content_hash().encode())
    for dep in sorted(graph.edges.get(block.id, ())):
        h.update(keys.get(dep, "").encode())
    return h.hexdigest()


def _render_text(block: Block, ns: dict) -> str:
    """Substitute ``@val:name`` with live values; leave other cites for Typst."""
    from ..prose import CITE_RE, literal, read_text, transform
    import re

    def sub(m):
        kind, target = m.group("kind"), m.group("target")
        if kind == "val":
            if target in ns:
                return literal(fmt_quantity(ns[target])) + ("#[;]" if m["tail"] else "")
            return f"?{target}?" + m["tail"]
        return m.group(0)

    pattern = re.compile(CITE_RE.pattern + r"(?P<tail>;?)")
    return transform(read_text(block.source, ns), lambda part: pattern.sub(sub, part))


_EXPECTED = {"plot": "Figure", "table": "Table", "draw": "Drawing",
             "sources": "Sources", "requirements": "Requirements"}


def _pick_content(block: Block, ns: dict, before: set[str], expression=None):
    """Find the rich-content object a content block bound.

    Source order, not set order: iterating ``block.defs`` (a frozenset) would
    make the choice -- and therefore the rendered PDF -- unstable.
    """
    from ..content import Drawing, Figure, Sources, Table
    from ..math.calc import last_assigned_names
    from ..req import Requirements
    from ..sheets import Constants, Sheet

    want = {"plot": Figure, "table": Table, "draw": Drawing,
            "sources": Sources, "requirements": Requirements}[block.kind]

    def content(value):
        if want is Table and isinstance(value, (Constants, Sheet)):
            return value.table()
        return value if isinstance(value, want) else None

    if expression is not None:
        value = content(expression)
        if value is None:
            raise ValueError(
                f"{block.kind} cell's last expression must produce a "
                f"{_EXPECTED[block.kind]}; got {type(expression).__name__}"
            )
        return value
    if not block.source.strip():
        # An empty content cell places something built elsewhere -- a sheet that
        # renders its own table, a drawing generated by the CAD module. The
        # cell is then only a position, which is all the document should say.
        value = ns.get(block.id)
        return content(value)
    names = last_assigned_names(block.source) or sorted(block.defs)
    for name in names:
        if name in before and name not in block.defs:
            continue
        value = content(ns.get(name))
        if value is not None:
            return value
    return None


def _render_symbolic(block: Block, ns: dict) -> str:
    """Render the sympy expressions a symbolic block bound, via TypstPrinter."""
    import sympy as sp

    from ..math.calc import last_assigned_names

    lines: list[str] = []
    # Source order, not set order: block.defs is a frozenset and iterating it
    # would make the rendered output (and therefore the PDF bytes) unstable.
    for name in last_assigned_names(block.source):
        val = ns.get(name)
        if isinstance(val, sp.Basic) and not isinstance(val, sp.Symbol):
            lines.append(f"{typst_math(sp.Symbol(name))} = {typst_math(val)}")
        elif isinstance(val, (sp.Eq, sp.Rel)):
            lines.append(typst_math(val))
    return " \\\n".join(lines)


def execute(
    doc: Document,
    *,
    only: set[str] | None = None,
    previous: dict[str, BlockResult] | None = None,
) -> Document:
    """Run the document. ``only`` limits execution to those block ids."""
    ns = doc.namespace or fresh_namespace()
    doc.namespace = ns
    previous = previous or {}
    if doc.packet is not None:
        doc.blocks = list(doc.packet.authored)
        ns.update(doc.packet.load(doc))
        previous = {}  # Packet inputs are external files; re-read them on every build.

    from ..req.model import document_dir

    doc_dir = doc.path.parent if doc.path and doc.path.name != "<string>" else None
    ns.setdefault("__name__", "__kip_document__")
    ns.setdefault("__file__", str(doc.path.resolve()) if doc.path else "<string>")
    import sys
    old_path = sys.path[:]
    # Each report may have its own analysis.py/cad.py. Do not reuse another
    # project's imports (or stale workbook inputs) in repeated API builds.
    local_names = {p.stem for p in doc_dir.glob("*.py")} if doc_dir else set()
    saved_modules = {name: module for name, module in sys.modules.copy().items()
                     if name.split(".")[0] in local_names and name != "__main__"}
    for name in saved_modules:
        del sys.modules[name]
    if doc_dir:
        sys.path.insert(0, str(doc_dir.resolve()))
    with document_dir(doc_dir):
        try:
            return _execute_ordered(doc, ns, previous, only)
        finally:
            sys.path[:] = old_path
            for name in list(sys.modules):
                if name.split(".")[0] in local_names and name != "__main__":
                    del sys.modules[name]
            sys.modules.update(saved_modules)


def _execute_ordered(doc, ns, previous, only):
    keys: dict[str, str] = {}
    results: dict[str, BlockResult] = {}
    for bid in doc.graph.order:
        block = doc.graph.by_id(bid)
        key = _cache_key(block, doc.graph, keys)
        keys[bid] = key

        if doc.packet is not None:
            from ..packet import MissingInput
            unavailable = [ns[name].reason for name in block.refs if isinstance(ns.get(name), MissingInput)]
            dependencies = [name for name in doc.graph.edges[bid]
                            if results[name].state in ("OPEN", "BLOCKED") or results[name].failed]
            if unavailable or dependencies:
                reason = "; ".join(dict.fromkeys(unavailable)) or "Waiting on " + ", ".join(sorted(dependencies)) + "."
                results[bid] = BlockResult(bid, block.kind, state="BLOCKED", reason=reason, cache_key=key)
                continue

        cached = previous.get(bid)
        if cached is not None and cached.cache_key == key and (only is None or bid not in only):
            results[bid] = cached
            # a cached block's bindings must still exist in the namespace
            for name, val in cached.values.items():
                ns[name] = val
            continue

        results[bid] = _run_block(block, ns, key, draft=doc.packet is not None)

    doc.results = results
    # Presentation-only requests can precede the quantities they describe.
    # Resolve them after execution, also when their own cell was cached.
    quantities = [item for block in doc.ordered_blocks()
                  for item in results[block.id].quantities.values()]
    for bid, result in list(results.items()):
        if result.derived is not None:
            try:
                results[bid] = replace(result, content=result.derived.resolve(quantities),
                                       ok=True, error=None)
            except (ValueError, TypeError) as exc:
                results[bid] = replace(result, ok=False, error=str(exc))
    if doc.packet is not None:
        doc.packet.finish(doc)
    return doc


def _controlled_rows(block: Block, ns: dict) -> list:
    """Match names bound by this block back to the controlled variables read.

    These cells are rendered with their provenance rather than as arithmetic:
    value, levying requirement, and owning item.
    """
    import ast

    from ..math.calc import last_assigned_names

    sources: dict[str, str] = {}
    try:
        tree = ast.parse(block.source)
    except SyntaxError:
        tree = None
    if tree is not None:
        for node in ast.walk(tree):
            if (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)
                    and isinstance(node.value, ast.Attribute)):
                sources[node.targets[0].id] = node.value.attr

    rows = []
    for name in last_assigned_names(block.source):
        var = None
        attr = sources.get(name)
        for reqs in _all_requirements(ns):
            if attr:
                var = reqs.var(attr, strict=False)
            if var is not None:
                break
        if var is not None:
            rows.append((name, ns.get(name), var))
    return rows


def _all_requirements(ns: dict):
    """Every Requirements object bound in the document namespace."""
    from ..req import Requirements

    seen, out = set(), []
    for value in ns.values():
        if isinstance(value, Requirements) and id(value) not in seen:
            seen.add(id(value))
            out.append(value)
    return out


def _new_checks(ns: dict, before: list[int]) -> list:
    """Checks recorded since the snapshot, across every Requirements object."""
    out = []
    for i, reqs in enumerate(_all_requirements(ns)):
        start = before[i] if i < len(before) else 0
        out.extend(reqs.checks[start:])
    return out


def _run_block(block: Block, ns: dict, key: str, *, draft=False) -> BlockResult:
    res = BlockResult(block_id=block.id, kind=block.kind, cache_key=key)
    before = set(ns)
    checks_before = [len(r.checks) for r in _all_requirements(ns)]

    expression = None
    from ..quantities import AutoNomenclature, collect_reads, symbol_entries
    reads = []
    if block.is_code and block.source.strip():
        try:
            import ast

            tree = ast.parse(block.source, f"<{block.id}>")
            tail = None
            if (tree.body and (block.has_content or block.kind in ("calc", "calculation"))
                    and isinstance(tree.body[-1], ast.Expr)):
                tail = tree.body.pop().value
            with collect_reads() as reads:
                exec(compile(tree, f"<{block.id}>", "exec"), ns)
                if tail is not None:
                    expression = eval(compile(ast.Expression(tail), f"<{block.id}>", "eval"), ns)
        except Exception as e:
            from ..packet import UnavailableInput
            if draft and (isinstance(e, UnavailableInput) or
                          (block.kind == "draw" and isinstance(e, FileNotFoundError))):
                res.state = "OPEN" if block.kind == "draw" else "BLOCKED"
                res.reason = str(e)
                return res
            res.ok = False
            res.error = f"{type(e).__name__}: {e}"
            res.traceback = traceback.format_exc(limit=3)
            return res

    new_names = set(ns) - before
    # Engineering variables routinely reuse unit names (A, L, W, ...).
    # Include bindings assigned by this block even when a name already existed.
    res.values = {n: ns[n] for n in sorted(new_names | set(block.defs))
                  if n in ns and not n.startswith("_")}

    try:
        from ..authoring import Calculation
        calculations = [v for v in res.values.values() if isinstance(v, Calculation)]
        if isinstance(expression, Calculation):
            calculations = [expression]
        if block.kind == "calculation" and not calculations:
            raise CalcRenderError("calculation cell must return or bind a @calculation result")
        if block.kind in ("calc", "calculation") and calculations:
            if len(calculations) != 1:
                raise CalcRenderError("bind one decorated calculation per cell")
            calculation = calculations[0]
            res.calculation = calculation
            rendered = render_calc(calculation.source, calculation.values,
                                   precision=calculation.precision)
            res.equations = rendered.equations
        elif block.renders_math and block.source.strip():
            from ..math.calc import display_units
            # `# -> MPa` beside the equation says what unit to read it in.
            shown, annotated = display_units(block.source)
            rendered = render_calc(shown, ns, precision=block.precision,
                                   result_units=annotated + block.result_units)
            res.equations = rendered.equations
            # refresh values after any unit conversion
            for n in rendered.converted:
                if n in ns:
                    res.values[n] = ns[n]
        elif block.kind == "symbolic":
            res.typst = _render_symbolic(block, ns)
        elif block.kind == "text":
            res.text = _render_text(block, ns)
        elif block.kind == "controlled":
            res.controlled = _controlled_rows(block, ns)
            if not res.controlled:
                res.ok = False
                res.error = (
                    "kip.controlled block bound no controlled variables; "
                    "assign them from a Requirements object, e.g. "
                    "P = reqs.P_design"
                )
        elif block.kind == "verify":
            res.checks = _new_checks(ns, checks_before)
            if not res.checks:
                res.ok = False
                res.error = (
                    "kip.verify block recorded no checks; call "
                    "reqs.verify(\"REQ-ID\", value, \">= 0\")"
                )
        elif block.has_content:
            res.content = _pick_content(block, ns, before, expression)
            if isinstance(res.content, AutoNomenclature):
                res.derived = res.content
            if res.content is None and not block.source.strip():
                res.ok = False
                res.error = (
                    f"empty {block.kind} cell places {block.id!r}, but no "
                    f"{_EXPECTED[block.kind]} of that name exists; either "
                    "build it earlier or give the cell a body"
                )
            elif res.content is None:
                res.ok = False
                res.error = (
                    f"kip.{block.kind} block must bind a "
                    f"{_EXPECTED[block.kind]} object; none of "
                    f"{sorted(block.defs) or ['(nothing)']} is one"
                )
        if res.calculation is not None:
            res.quantities = res.calculation.symbols
        elif block.kind in ("given", "controlled", "calc"):
            res.quantities = {name: item for name, item in symbol_entries(block.source, ns, reads).items()
                              if name in block.defs}
            if block.kind == "calc" and len(res.quantities) == 1 and block.meta.get("label"):
                name, item = next(iter(res.quantities.items()))
                if not item.description:
                    res.quantities[name] = replace(item, description=block.meta["label"], description_inferred=True)
    except CalcRenderError as e:
        res.ok = False
        res.error = str(e)
    except Exception as e:
        res.ok = False
        res.error = f"{type(e).__name__}: {e}"
        res.traceback = traceback.format_exc(limit=3)

    return res


def _citation_diagnostics(blocks: list[Block], path) -> list[Diagnostic]:
    """Warn about @blk:/@val: references that point at nothing."""
    known = {b.id for b in blocks}
    defined: set[str] = set()
    for b in blocks:
        defined |= set(b.defs)

    out: list[Diagnostic] = []
    for b in blocks:
        for kind, target in b.cites:
            if kind == "blk" and target not in known:
                out.append(Diagnostic(
                    "warning", b.id, b.body_start,
                    f"@blk:{target} refers to no such block",
                    "rendered as plain text; check the block id",
                ))
            elif kind == "val" and target not in defined:
                out.append(Diagnostic(
                    "warning", b.id, b.body_start,
                    f"@val:{target} refers to no defined value",
                    "rendered as ?{}? in the document".format(target),
                ))
    return out


def build(
    path: str | Path | None = None,
    *,
    source: str | None = None,
    strict: bool = True,
) -> Document:
    """Parse, validate, analyse and execute a document.

    ``strict`` raises on validation errors or failed blocks; ``strict=False`` collects errors for inspection instead.
    """
    if source is None:
        if path is None:
            raise ValueError("build() needs either path= or source=")
        p = Path(path)
        text = p.read_text(encoding="utf-8")
        blocks = parse(text, p)
    else:
        p = Path(path) if path else Path("<string>")
        text = source
        blocks = parse(source, p)

    from ..packet import prepare
    from .graph import default_provided
    packet = prepare(blocks, p)
    if packet is not None:
        blocks = list(packet.authored)
    graph = analyze(blocks, provided=default_provided() | ({"C", "reqs"} if packet else set()))
    diags = validate_all(blocks, p)
    diags.extend(_citation_diagnostics(blocks, p))
    doc = Document(path=p, source=text, blocks=blocks, graph=graph, diagnostics=diags, packet=packet)

    if strict and doc.errors:
        from .validate import ValidationError

        raise ValidationError(doc.errors, p)

    execute(doc)

    if strict and doc.errors:
        from .validate import ValidationError
        raise ValidationError(doc.errors, p)

    if strict and any(r.failed for r in doc.results.values()):
        raise ExecutionError(list(doc.results.values()), p)
    return doc


run = build
