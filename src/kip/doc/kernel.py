"""Execute dependency-ordered blocks and cache their results."""

from __future__ import annotations

import traceback
from dataclasses import dataclass, field
from pathlib import Path

from ..math.handcalc_bridge import CalcRenderError, render_calc
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
    latex: str | None = None          # handcalcs output (mitex body), wide form
    latex_long: str | None = None     # stacked form, for narrow columns
    typst: str | None = None          # native Typst math (symbolic blocks)
    text: str | None = None           # resolved prose
    content: object | None = None     # Figure / Table / Drawing / Sources
    checks: list = field(default_factory=list)   # verification results
    #: (name, value, controlled-variable) triples for a kip.controlled block
    controlled: list = field(default_factory=list)
    values: dict[str, object] = field(default_factory=dict)
    error: str | None = None
    traceback: str | None = None
    cache_key: str = ""

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
    from .graph import CITE_RE

    def sub(m):
        kind, target = m.group("kind"), m.group("target")
        if kind == "val":
            if target in ns:
                return fmt_quantity(ns[target])
            return f"?{target}?"
        return m.group(0)

    src = block.source.strip()
    # a bare string literal body is the common form for prose blocks
    if src.startswith(('"""', "'''", '"', "'")):
        try:
            import ast as _ast

            parsed = _ast.literal_eval(src)
            if isinstance(parsed, str):
                src = parsed
        except (ValueError, SyntaxError):
            pass
    return CITE_RE.sub(sub, src)


_EXPECTED = {"plot": "Figure", "table": "Table", "draw": "Drawing",
             "sources": "Sources", "requirements": "Requirements"}


def _pick_content(block: Block, ns: dict, before: set[str]):
    """Find the rich-content object a content block bound.

    Source order, not set order: iterating ``block.defs`` (a frozenset) would
    make the choice -- and therefore the rendered PDF -- unstable.
    """
    from ..content import Drawing, Figure, Sources, Table
    from ..math.handcalc_bridge import last_assigned_names
    from ..req import Requirements

    want = {"plot": Figure, "table": Table, "draw": Drawing,
            "sources": Sources, "requirements": Requirements}[block.kind]
    names = last_assigned_names(block.source) or sorted(block.defs)
    for name in names:
        if name in before and name not in block.defs:
            continue
        value = ns.get(name)
        if isinstance(value, want):
            return value
    return None


def _render_symbolic(block: Block, ns: dict) -> str:
    """Render the sympy expressions a symbolic block bound, via TypstPrinter."""
    import sympy as sp

    from ..math.handcalc_bridge import last_assigned_names

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

        cached = previous.get(bid)
        if cached is not None and cached.cache_key == key and (only is None or bid not in only):
            results[bid] = cached
            # a cached block's bindings must still exist in the namespace
            for name, val in cached.values.items():
                ns[name] = val
            continue

        results[bid] = _run_block(block, ns, key)

    doc.results = results
    return doc


def _controlled_rows(block: Block, ns: dict) -> list:
    """Match names bound by this block back to the controlled variables read.

    Reading ``reqs.P_design`` is attribute access, which handcalcs renders
    wrongly, so these blocks bypass handcalcs entirely and are rendered with
    their provenance instead: value, levying requirement, and owning item.
    """
    import ast

    from ..math.handcalc_bridge import last_assigned_names

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


def _run_block(block: Block, ns: dict, key: str) -> BlockResult:
    res = BlockResult(block_id=block.id, kind=block.kind, cache_key=key)
    before = set(ns)
    checks_before = [len(r.checks) for r in _all_requirements(ns)]

    if block.is_code and block.source.strip():
        try:
            exec(compile(block.source, f"<{block.id}>", "exec"), ns)
        except Exception as e:
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
        if block.kind == "calculation" and not calculations:
            raise CalcRenderError("calculation cell must bind a @calculation result")
        if block.kind in ("calc", "calculation") and calculations:
            if len(calculations) != 1:
                raise CalcRenderError("bind one decorated calculation per cell")
            calculation = calculations[0]
            rendered = render_calc(calculation.source, calculation.values,
                                   precision=calculation.precision)
            res.latex, res.latex_long = rendered.latex, rendered.latex_long
        elif block.uses_handcalcs and block.source.strip():
            rendered = render_calc(
                block.source, ns,
                precision=block.precision,
                result_units=block.result_units,
                # "params" is handcalcs' compact input-listing mode: a bare
                # `x = 5 mm` needs no substitution/result columns.
                override=block.meta.get(
                    "display", "params" if block.kind == "given" else ""),
            )
            res.latex = rendered.latex
            res.latex_long = rendered.latex_long
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
            res.content = _pick_content(block, ns, before)
            if res.content is None:
                res.ok = False
                res.error = (
                    f"kip.{block.kind} block must bind a "
                    f"{_EXPECTED[block.kind]} object; none of "
                    f"{sorted(block.defs) or ['(nothing)']} is one"
                )
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

    graph = analyze(blocks)
    diags = validate_all(blocks, p)
    diags.extend(_citation_diagnostics(blocks, p))
    doc = Document(path=p, source=text, blocks=blocks, graph=graph, diagnostics=diags)

    if strict and doc.errors:
        from .validate import ValidationError

        raise ValidationError(doc.errors, p)

    execute(doc)

    if strict and any(r.failed for r in doc.results.values()):
        raise ExecutionError(list(doc.results.values()), p)
    return doc


run = build
