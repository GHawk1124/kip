"""Execute a document's cells and record what each one produced.

Cells run in the order :func:`kip.doc.graph.execution_order` gives:
calculations top to bottom, then presentation top to bottom. A cell whose
inputs failed or are missing is recorded as BLOCKED, naming what it waits on,
instead of being run into a confusing NameError.
"""

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
    #: PRESENT, or OPEN (expected material missing) / BLOCKED (waiting on inputs)
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
        blocked = [r for r in results if r.state == "BLOCKED"]
        super().__init__(
            f"{len(failures)} block(s) failed in {path}:\n"
            + "\n".join(f"  [{r.block_id}] {r.error}" for r in failures)
            + (f"\n  ({len(blocked)} more waiting on them)" if blocked else "")
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
    #: conventions layered on the kernel (see kip.doc.extension)
    extensions: list = field(default_factory=list)
    #: the cells as authored; an extension's finish() may replace ``blocks``
    authored: list[Block] = field(default_factory=list)

    def __post_init__(self):
        if not self.authored:
            self.authored = list(self.blocks)

    @property
    def draft(self) -> bool:
        """Missing declared inputs are OPEN/BLOCKED rather than errors."""
        return any(ext.draft for ext in self.extensions)

    @property
    def packet(self):
        """The component packet extension, if the document declared one."""
        from ..packet import ComponentPacket
        return next((e for e in self.extensions if isinstance(e, ComponentPacket)), None)

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


def execute(doc: Document) -> Document:
    """Run the document's cells and store their results on ``doc``."""
    from .context import building

    doc_dir = doc.path.parent if doc.path and doc.path.name != "<string>" else None
    with building(doc_dir) as ctx:
        ns = fresh_namespace()
        ns["__builtins__"] = ctx.builtins()  # `import analysis` finds this project's
        ns["__name__"] = "__kip_document__"
        ns["__file__"] = str(doc.path.resolve()) if doc.path else "<string>"
        doc.namespace = ns
        doc.blocks = list(doc.authored)
        for extension in doc.extensions:
            ns.update(extension.load(doc))  # external files: re-read every build
        _execute_ordered(doc, ns)
    return doc


def _waiting(block: Block, ns: dict, graph: DependencyGraph,
             results: dict[str, BlockResult]) -> str | None:
    """Why ``block`` cannot run yet, or None when its inputs are all there."""
    from .extension import MissingInput

    missing = [ns[name].reason for name in sorted(block.refs)
               if isinstance(ns.get(name), MissingInput)]
    if missing:
        return "; ".join(dict.fromkeys(missing))
    stuck = sorted(dep for dep in graph.edges.get(block.id, ())
                   if dep in results and (results[dep].failed
                                          or results[dep].state in ("OPEN", "BLOCKED")))
    if stuck:
        failed = [d for d in stuck if results[d].failed]
        return ("Waiting on " + ", ".join(stuck)
                + (", which failed." if failed and len(failed) == len(stuck) else "."))
    return None


def _report_notes(doc, block) -> None:
    """Deprecations raised while ``block`` ran become document warnings."""
    from .context import current
    ctx = current()
    if ctx is None:
        return
    for note in ctx.notes:
        if not any(d.message == note for d in doc.diagnostics):
            doc.diagnostics.append(Diagnostic("warning", block.id, block.body_start, note))


def _execute_ordered(doc, ns):
    results: dict[str, BlockResult] = {}
    doc.results = results
    for bid in doc.graph.order:
        block = doc.graph.by_id(bid)
        reason = _waiting(block, ns, doc.graph, results)
        if reason is not None:
            results[bid] = BlockResult(bid, block.kind, state="BLOCKED", reason=reason)
            continue
        results[bid] = _run_block(block, ns, draft=doc.draft)
        _report_notes(doc, block)

    # Presentation-only requests can precede the quantities they describe.
    quantities = [item for block in doc.ordered_blocks()
                  for item in results[block.id].quantities.values()]
    for bid, result in list(results.items()):
        if result.derived is not None:
            try:
                results[bid] = replace(result, content=result.derived.resolve(quantities),
                                       ok=True, error=None)
            except (ValueError, TypeError) as exc:
                results[bid] = replace(result, ok=False, error=str(exc))
    for extension in doc.extensions:
        extension.finish(doc)
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


def _run_block(block: Block, ns: dict, *, draft=False) -> BlockResult:
    res = BlockResult(block_id=block.id, kind=block.kind)
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
            from .extension import UnavailableInput
            if draft and (isinstance(e, UnavailableInput) or
                          (block.kind == "draw" and isinstance(e, FileNotFoundError))):
                res.state = "OPEN" if block.kind == "draw" else "BLOCKED"
                res.reason = str(e)
                return res
            res.ok = False
            res.error = f"{type(e).__name__}: {e}"
            res.traceback = _user_traceback()
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
        if not calculations and block.kind in ("calc", "calculation") and block.source.strip():
            import ast
            from ..math.calc import is_external_call
            tree = ast.parse(block.source)
            if is_external_call(tree):
                call = tree.body[0].value
                name = f"{call.func.value.id}.{call.func.attr}"
                raise CalcRenderError(
                    f"{name}(...) did not return an @calculation result; decorate "
                    "that function with @calculation, or for plain arithmetic call "
                    "bare function names such as sqrt(x)")
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
        res.traceback = _user_traceback()

    return res


def _user_traceback() -> str:
    """The whole traceback; :func:`where` picks the author's frame out of it."""
    return traceback.format_exc()


def where(result: BlockResult) -> str | None:
    """``file:line`` of the innermost frame outside kip itself, if any."""
    import re

    import sysconfig

    frames = re.findall(r'File "([^"]+)", line (\d+)', result.traceback or "")
    library = [str(Path(__file__).resolve().parents[1])] + [
        str(Path(p).resolve()) for key, p in sysconfig.get_paths().items()
        if key in ("stdlib", "platstdlib", "purelib", "platlib")]
    for file, line in reversed(frames):
        resolved = str(Path(file).resolve()) if not file.startswith("<") else file
        if file.startswith("<") or any(resolved.startswith(root) for root in library):
            continue
        return f"{file}:{line}"
    return None


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


def _early_use_diagnostics(blocks: list[Block], graph: DependencyGraph) -> list[Diagnostic]:
    """A calculation reading a name that only a later cell defines."""
    out = []
    for b in blocks:
        for name, later in graph.early.get(b.id, ()):
            producer = graph.by_id(later)
            where = f"cell {later!r} (line {producer.marker_line})"
            out.append(Diagnostic(
                "error", b.id, b.body_start,
                f"{name!r} is used before it is defined; {where} defines it later",
                "calculations run top to bottom, before tables, plots, drawings "
                "and text; move this cell below the one that defines it",
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

    from .extension import plan
    from .graph import default_provided
    blocks, extensions = plan(blocks, p)
    provided = default_provided().union(*(e.provided for e in extensions))
    graph = analyze(blocks, provided=provided)
    diags = validate_all(blocks, p)
    diags.extend(Diagnostic("warning", b.id, b.marker_line, note)
                 for b in blocks for note in b.notes)
    diags.extend(_citation_diagnostics(blocks, p))
    diags.extend(_early_use_diagnostics(blocks, graph))
    from .validate import unit_diagnostics
    diags.extend(unit_diagnostics(blocks))
    doc = Document(path=p, source=text, blocks=blocks, graph=graph, diagnostics=diags,
                   extensions=extensions)

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
