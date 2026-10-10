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
    #: ``assert`` checks in a calculation (math.calc.Check), with absolute lines
    assertions: list = field(default_factory=list)
    #: (name, value, controlled-variable) triples for a kip.controlled block
    controlled: list = field(default_factory=list)
    values: dict[str, object] = field(default_factory=dict)
    error: str | None = None
    traceback: str | None = None
    #: ``file:line`` of a failure found without a traceback (a calc that will not render)
    location: str | None = None
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
            + "\n".join(f"  {where(r) or path}: [{r.block_id}] {r.error}" for r in failures)
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
    from ..prose import CITE_RE, escape_literals, literal, read_text, transform
    import re

    def sub(m):
        kind, target = m.group("kind"), m.group("target")
        if kind == "val":
            if target in ns:
                return literal(fmt_quantity(ns[target])) + ("#[;]" if m["tail"] else "")
            return f"?{target}?" + m["tail"]
        return m.group(0)

    pattern = re.compile(CITE_RE.pattern + r"(?P<tail>;?)")
    text = escape_literals(read_text(block.source, ns))
    return transform(text, lambda part: pattern.sub(sub, part))


_EXPECTED = {"plot": "Figure", "table": "Table", "draw": "Drawing",
             "sources": "Sources", "requirements": "Requirements"}


def _pick_content(block: Block, ns: dict, before: set[str], expression=None):
    """Find the rich-content object a content block bound.

    Source order, not set order: iterating ``block.defs`` (a frozenset) would
    make the choice -- and therefore the rendered PDF -- unstable.
    """
    from ..content import Drawing, Figure, Listing, Sources, Table
    from ..math.calc import last_assigned_names
    from ..req import Requirements
    from ..sheets import Constants, Sheet

    want = {"plot": Figure, "table": Table, "draw": (Drawing, Listing),
            "sources": Sources, "requirements": Requirements}[block.kind]

    def content(value):
        if want is Table and isinstance(value, (Constants, Sheet)):
            return value.table()
        if hasattr(type(value), "kip_content"):
            value = value.kip_content(block.kind)  # a molecule, schematic, board, signal...
        else:
            from ..adapters import adapt
            value = adapt(value, block.kind)  # schemdraw, matplotlib, SKiDL
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
        if doc.path and not doc.path.name.startswith("<"):
            # Cells are compiled under doc.py's own name and lines, so a
            # traceback shows the author's line, as built, not the file on disk.
            import linecache
            linecache.cache[str(doc.path)] = (len(doc.source), None,
                                              doc.source.splitlines(True), str(doc.path))
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
        filename = str(doc.path) if doc.path and not doc.path.name.startswith("<") else None
        results[bid] = _run_block(block, ns, draft=doc.draft, filename=filename)
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


def _failure(e: Exception) -> str:
    return str(e) if isinstance(e, CalcRenderError) else f"{type(e).__name__}: {e}"


def _statement_at(tree, line: int):
    """The author's simple statement spanning ``line``, or the ``if`` test there.

    The first, not the last: a ``# -> unit`` conversion kip inserts after an
    assignment carries the assignment's line too.
    """
    import ast
    for node in ast.walk(tree):
        if isinstance(node, (ast.If, ast.While)):
            node = node.test
        elif not isinstance(node, ast.stmt) or hasattr(node, "body"):
            continue
        if node.lineno <= line <= (node.end_lineno or node.lineno):
            return node
    return None


def _explain_dimensions(e: Exception, filename: str, tree, ns: dict, renders_math: bool) -> str | None:
    """Which ``+``, ``-`` or comparison mixed dimensions, innermost frame first.

    Only arithmetic kip renders is looked at again: a calc cell's own lines,
    and the body of an ``@calculation`` function -- in its own file, with the
    values of that call.
    """
    import ast
    import linecache
    from ..authoring import calculation_code
    from ..math.calc import explain_dimensions

    frames, tb = [], e.__traceback__
    while tb is not None:
        frames.append((tb.tb_frame, tb.tb_lineno))
        tb = tb.tb_next
    for frame, line in reversed(frames):
        code = frame.f_code
        if code in calculation_code:
            try:
                source = ast.parse("".join(linecache.getlines(code.co_filename)))
            except SyntaxError:
                continue
            statement, values = _statement_at(source, line), {**frame.f_globals, **frame.f_locals}
        elif renders_math and code.co_filename == filename:
            statement, values = _statement_at(tree, line), ns
        else:
            continue
        explained = statement is not None and explain_dimensions(statement, values)
        if explained:
            return explained
    return None


def _run_block(block: Block, ns: dict, *, draft=False, filename: str | None = None) -> BlockResult:
    res = BlockResult(block_id=block.id, kind=block.kind)
    filename = filename or f"<{block.id}>"
    before = set(ns)
    checks_before = [len(r.checks) for r in _all_requirements(ns)]

    expression = None
    from ..quantities import AutoNomenclature, collect_reads, symbol_entries
    reads = []
    if block.is_code and block.source.strip():
        try:
            import ast

            tree = ast.parse(block.source, filename)
            ast.increment_lineno(tree, block.body_start - 1)
            if block.renders_math:
                from ..math.calc import display_units, strip_checks, with_conversions
                with_conversions(tree.body, display_units(block.source)[1])
                strip_checks(tree.body)
            tail = None
            if (tree.body and (block.has_content or block.kind in ("calc", "calculation"))
                    and isinstance(tree.body[-1], ast.Expr)):
                tail = tree.body.pop().value
            with collect_reads() as reads:
                exec(compile(tree, filename, "exec"), ns)
                if tail is not None:
                    expression = eval(compile(ast.Expression(tail), filename, "eval"), ns)
        except Exception as e:
            from .extension import UnavailableInput
            if draft and (isinstance(e, UnavailableInput) or
                          (block.kind == "draw" and isinstance(e, FileNotFoundError))):
                res.state = "OPEN" if block.kind == "draw" else "BLOCKED"
                res.reason = str(e)
                return res
            res.ok = False
            res.error = _failure(e)
            res.traceback = _user_traceback()
            from ..math.calc import mixes_units
            if mixes_units(e):
                res.error = _explain_dimensions(e, filename, tree, ns, block.renders_math) or res.error
            return res

    new_names = set(ns) - before
    origin = (filename, block.body_start)  # where rendered line 1 is
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
            origin = calculation.origin
            rendered = render_calc(calculation.source, {**calculation.constants, **calculation.values},
                                   precision=calculation.precision)
            res.equations = rendered.equations
            file, first = calculation.origin
            res.assertions = [replace(c, line=first - 1 + c.line, file=file)
                              for c in rendered.checks]
            rest = _beside_calculation(block.source, calculation, ns)
            if rest.strip():  # the cell's own lines after it: checks on its results, mostly
                from ..math.calc import display_units
                shown, annotated = display_units(rest)
                more = render_calc(shown, ns, precision=block.precision,
                                   result_units=annotated + block.result_units)
                res.equations = res.equations + more.equations
                res.assertions += [replace(c, line=block.body_start - 1 + c.line)
                                   for c in more.checks]
                for n in more.converted:
                    if n in ns:
                        res.values[n] = ns[n]
        elif block.renders_math and block.source.strip():
            from ..math.calc import display_units
            # `# -> MPa` beside the equation says what unit to read it in.
            shown, annotated = display_units(block.source)
            rendered = render_calc(shown, ns, precision=block.precision,
                                   result_units=annotated + block.result_units)
            res.equations = rendered.equations
            res.assertions = [replace(c, line=block.body_start - 1 + c.line)
                              for c in rendered.checks]
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
        if block.kind in ("calc", "calculation") and block.meta.get("result"):
            values = res.calculation.values if res.calculation is not None else res.values
            missing = [n for n in result_names(block, res) if n not in values]
            if missing:
                from ..math.calc import last_assigned_names
                computed = last_assigned_names(res.calculation.source if res.calculation
                                               else block.source)
                origin = (filename, block.marker_line)  # the marker carries result=
                raise CalcRenderError(
                    f"result={block.meta['result']} names {', '.join(missing)}, which this "
                    f"cell does not compute (it computes {', '.join(computed) or 'nothing'})",
                    lineno=1)
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
        if e.lineno is not None:
            res.location = f"{origin[0]}:{origin[1] - 1 + e.lineno}"
    except Exception as e:
        res.ok = False
        res.error = _failure(e)
        res.traceback = _user_traceback()

    return res


def _beside_calculation(source: str, calculation, ns: dict) -> str:
    """A calc cell's source with the statement that bound ``calculation`` blanked.

    Lines keep their numbers, so a failing check still points at its line.
    """
    import ast
    tree = ast.parse(source)
    lines = source.splitlines()
    binding = [s for s in tree.body if isinstance(s, ast.Assign) and len(s.targets) == 1
               and isinstance(s.targets[0], ast.Name) and ns.get(s.targets[0].id) is calculation]
    if not binding and tree.body and isinstance(tree.body[-1], ast.Expr):
        binding = [tree.body[-1]]  # shown bare as the cell's last line
    for stmt in binding:
        for k in range(stmt.lineno - 1, stmt.end_lineno or stmt.lineno):
            lines[k] = ""
    return "\n".join(lines)


def result_names(block: Block, result: BlockResult) -> list[str]:
    """The names a calc cell's result boxes show: its ``result=``, else its last value."""
    from ..math.calc import last_assigned_names

    calculation = result.calculation
    source = calculation.source if calculation is not None else block.source
    values = calculation.values if calculation is not None else result.values
    wanted = block.meta.get("result", "").strip()
    if wanted.lower() == "none":
        return []
    if wanted:
        return [n.strip() for n in wanted.split(",") if n.strip()]
    return [n for n in last_assigned_names(source) if n in values][-1:]


def _user_traceback() -> str:
    """The whole traceback; :func:`where` picks the author's frame out of it."""
    return traceback.format_exc()


def where(result: BlockResult) -> str | None:
    """``file:line`` of the innermost frame outside kip itself, if any."""
    import re

    if result.location:
        return result.location

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


def _cite_line(block: Block, kind: str, target: str) -> int:
    """The doc.py line holding ``@kind:target`` in ``block``."""
    import re
    pattern = re.compile(rf"@{kind}:{re.escape(target)}(?![A-Za-z0-9_\-])")
    for i, line in enumerate(block.source.splitlines()):
        if pattern.search(line):
            return block.body_start + i
    return block.body_start


def _unknown_cite(block: Block, kind: str, target: str, what: str,
                  known) -> Diagnostic:
    import difflib
    close = difflib.get_close_matches(target, sorted(known), n=1)
    hint = f"did you mean @{kind}:{close[0]}?" if close else ""
    return Diagnostic("error", block.id, _cite_line(block, kind, target),
                      f"@{kind}:{target} refers to {what}", hint)


def _citation_diagnostics(blocks: list[Block], provided=frozenset()) -> list[Diagnostic]:
    """@blk:/@val: references that point at nothing.

    A typo would otherwise ship as plain text or ``?name?`` in the PDF.
    """
    known = {b.id for b in blocks}
    defined: set[str] = set(provided)
    for b in blocks:
        defined |= set(b.defs)

    out: list[Diagnostic] = []
    for b in blocks:
        for kind, target in b.cites:
            if kind == "blk" and target not in known:
                out.append(_unknown_cite(b, kind, target, "no such block", known))
            elif kind == "val" and target not in defined:
                out.append(_unknown_cite(b, kind, target, "no defined value", defined))
    return out


def _source_citation_diagnostics(doc: Document) -> list[Diagnostic]:
    """@src:/@req: references to entries no loaded workbook holds.

    Both are only known once the document has run. While a reference list or
    requirements file is still OPEN in a draft, its citations are not judged.
    """
    from ..content import Sources

    cites = [(b, kind, target) for b in doc.blocks for kind, target in b.cites
             if kind in ("src", "req")]
    if not cites:
        return []
    keys: set[str] = set()
    sources_ready = True
    for b in doc.blocks:
        result = doc.results.get(b.id)
        if b.kind != "sources" or result is None:
            continue
        if isinstance(result.content, Sources):
            keys |= set(result.content)
        else:
            sources_ready = False
    from ..req import Requirements
    loaded = _all_requirements(doc.namespace) + [
        r.content for r in doc.results.values() if isinstance(r.content, Requirements)]
    ids: set[str] = set()
    for reqs in loaded:
        ids |= set(reqs.all_requirements())
    from .extension import MissingInput
    reqs_ready = not any(isinstance(v, MissingInput) for v in doc.namespace.values())

    out: list[Diagnostic] = []
    for b, kind, target in cites:
        if kind == "src" and sources_ready and target not in keys:
            what = "no reference in this document's sources" if keys else \
                "no reference; this document has no sources cell"
            out.append(_unknown_cite(b, kind, target, what, keys))
        elif kind == "req" and reqs_ready and ids and target not in ids:
            out.append(_unknown_cite(b, kind, target, "no loaded requirement", ids))
    return out


def _binding_line(block: Block, name: str) -> int:
    """The doc.py line where ``block`` first binds ``name``."""
    import ast
    try:
        tree = ast.parse(block.source)
    except SyntaxError:
        return block.body_start
    lines = [n.lineno for n in ast.walk(tree)
             if (isinstance(n, ast.Name) and not isinstance(n.ctx, ast.Load) and n.id == name)
             or (isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name == name)
             or (isinstance(n, ast.alias) and (n.asname or n.name).split(".")[0] == name)]
    return block.body_start - 1 + min(lines, default=1)


def _redefinition_diagnostics(blocks: list[Block]) -> list[Diagnostic]:
    """A name a calculation computes, bound again by another cell."""
    from .graph import redefinitions
    out = []
    for name, first, again in redefinitions(blocks):
        cell = "the prelude" if first.kind == "prelude" else f"cell {first.id!r}"
        out.append(Diagnostic(
            "error", again.id, _binding_line(again, name),
            f"{name!r} is already defined in {cell} (line {_binding_line(first, name)})",
            "give this value its own name; with two definitions, cells built "
            "later show a different value from the one printed where it was computed",
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
    diags.extend(_citation_diagnostics(blocks, provided))
    diags.extend(_early_use_diagnostics(blocks, graph))
    diags.extend(_redefinition_diagnostics(blocks))
    from .validate import unit_diagnostics
    diags.extend(unit_diagnostics(blocks))
    diags = list(dict.fromkeys(diags))  # one mistake, said once: f("a", "b") is one refusal
    doc = Document(path=p, source=text, blocks=blocks, graph=graph, diagnostics=diags,
                   extensions=extensions)

    if strict and doc.errors:
        from .validate import ValidationError

        raise ValidationError(doc.errors, p)

    execute(doc)
    doc.diagnostics.extend(_source_citation_diagnostics(doc))

    if strict and doc.errors:
        from .validate import ValidationError
        raise ValidationError(doc.errors, p)

    if strict and any(r.failed for r in doc.results.values()):
        raise ExecutionError(list(doc.results.values()), p)
    return doc


run = build
