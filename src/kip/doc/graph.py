"""Static dependency analysis over blocks, and their execution order.

Dependencies are derived by *reading* the code, never by running or tracing it:
each block's ``defs`` are the global names it binds and its ``refs`` are the
global names it reads without binding.

Cells run in two passes, each top to bottom. Calculations (the prelude,
inputs, calc, symbolic, controlled, verify and requirements cells) run first;
presentation (text, tables, plots, drawings and references) runs after them,
so prose and tables can show results from anywhere in the document. A
calculation that reads a name only a later cell defines is an error, reported
before anything runs, rather than whatever the name happened to hold.
"""

from __future__ import annotations

import ast
import builtins
import re
from dataclasses import dataclass, field

from .blocks import Block
from ..prose import CITE_RE, citations, text_template

__all__ = [
    "analyze",
    "default_provided",
    "analyze_code",
    "analyze_text",
    "execution_order",
    "PRESENTATION_KINDS",
    "CITE_RE",
    "DependencyGraph",
]

#: Kinds built in the second pass, after every calculation has run.
PRESENTATION_KINDS = frozenset({"text", "table", "plot", "draw", "sources"})

_BUILTINS = frozenset(dir(builtins))

#: ``@val:name`` inlines a computed value; ``@blk:id``/``@req:ID`` cross-reference.


class _ScopeVisitor(ast.NodeVisitor):
    """Collect module-level bindings and free (global) reads."""

    def __init__(self) -> None:
        self.defs: set[str] = set()
        self.loads: set[str] = set()
        #: loads that happen when the cell runs, not later inside a function body
        self.eager: set[str] = set()
        self._local_stack: list[set[str]] = []
        self._deferred = 0

    # -- helpers ---------------------------------------------------------
    def _bind(self, name: str) -> None:
        if self._local_stack:
            self._local_stack[-1].add(name)
        else:
            self.defs.add(name)

    def _bind_target(self, node: ast.AST) -> None:
        for n in ast.walk(node):
            if isinstance(n, ast.Name):
                self._bind(n.id)

    def _in_local(self, name: str) -> bool:
        return any(name in s for s in self._local_stack)

    # -- names -----------------------------------------------------------
    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load):
            if not self._in_local(node.id):
                self.loads.add(node.id)
                if not self._deferred:
                    self.eager.add(node.id)
        else:
            self._bind(node.id)

    # -- bindings --------------------------------------------------------
    def visit_Assign(self, node: ast.Assign) -> None:
        self.visit(node.value)
        for t in node.targets:
            self._bind_target(t)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value:
            self.visit(node.value)
        self._bind_target(node.target)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self.visit(node.value)
        if isinstance(node.target, ast.Name):
            self.loads.add(node.target.id)  # read-modify-write
            if not self._deferred:
                self.eager.add(node.target.id)
        self._bind_target(node.target)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self.visit(node.value)
        self._bind_target(node.target)

    def visit_For(self, node: ast.For) -> None:
        self.visit(node.iter)
        self._bind_target(node.target)
        for s in node.body + node.orelse:
            self.visit(s)

    def visit_With(self, node: ast.With) -> None:
        for item in node.items:
            self.visit(item.context_expr)
            if item.optional_vars:
                self._bind_target(item.optional_vars)
        for s in node.body:
            self.visit(s)

    def visit_Import(self, node: ast.Import) -> None:
        for a in node.names:
            self._bind(a.asname or a.name.split(".")[0])

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for a in node.names:
            if a.name == "*":
                continue  # star-import contributes unknown names; ignore
            self._bind(a.asname or a.name)

    # -- nested scopes ---------------------------------------------------
    def _visit_function(self, node) -> None:
        for d in node.decorator_list:
            self.visit(d)
        args = node.args
        for d in args.defaults + [x for x in args.kw_defaults if x]:
            self.visit(d)
        self._bind(node.name)
        local = {a.arg for a in args.posonlyargs + args.args + args.kwonlyargs}
        if args.vararg:
            local.add(args.vararg.arg)
        if args.kwarg:
            local.add(args.kwarg.arg)
        self._local_stack.append(local)
        self._deferred += 1
        for s in node.body:
            self.visit(s)
        self._deferred -= 1
        self._local_stack.pop()

    visit_FunctionDef = _visit_function
    visit_AsyncFunctionDef = _visit_function

    def visit_Lambda(self, node: ast.Lambda) -> None:
        args = node.args
        local = {a.arg for a in args.posonlyargs + args.args + args.kwonlyargs}
        if args.vararg:
            local.add(args.vararg.arg)
        if args.kwarg:
            local.add(args.kwarg.arg)
        self._local_stack.append(local)
        self._deferred += 1
        self.visit(node.body)
        self._deferred -= 1
        self._local_stack.pop()

    def _visit_comp(self, node) -> None:
        local: set[str] = set()
        for i, gen in enumerate(node.generators):
            # the outermost iterable is evaluated in the enclosing scope
            if i == 0:
                self.visit(gen.iter)
                self._local_stack.append(local)
            else:
                self.visit(gen.iter)
            for n in ast.walk(gen.target):
                if isinstance(n, ast.Name):
                    local.add(n.id)
            for cond in gen.ifs:
                self.visit(cond)
        if not node.generators:
            self._local_stack.append(local)
        for field in ("elt", "key", "value"):
            sub = getattr(node, field, None)
            if sub is not None:
                self.visit(sub)
        self._local_stack.pop()

    visit_ListComp = _visit_comp
    visit_SetComp = _visit_comp
    visit_GeneratorExp = _visit_comp
    visit_DictComp = _visit_comp

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for d in node.decorator_list + list(node.bases):
            self.visit(d)
        self._bind(node.name)
        self._local_stack.append(set())
        for s in node.body:
            self.visit(s)
        self._local_stack.pop()


def _visit(source: str) -> _ScopeVisitor | None:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    v = _ScopeVisitor()
    for stmt in tree.body:
        v.visit(stmt)
    return v


def analyze_code(source: str) -> tuple[frozenset[str], frozenset[str]]:
    """Return ``(defs, refs)`` for a block of Python source."""
    v = _visit(source)
    if v is None:
        return frozenset(), frozenset()
    refs = {n for n in v.loads if n not in v.defs and n not in _BUILTINS}
    return frozenset(v.defs), frozenset(refs)


def eager_refs(source: str) -> frozenset[str]:
    """Names read while the cell runs; reads inside a function body wait for a call."""
    v = _visit(source)
    return frozenset(n for n in v.eager if n not in _BUILTINS) if v else frozenset()


def analyze_text(source: str) -> tuple[frozenset[str], tuple[tuple[str, str], ...]]:
    """Return ``(refs, cites)`` for a prose block's ``@val:``/``@blk:``/``@req:``."""
    try:
        text, tree = text_template(source)
    except (SyntaxError, ValueError):
        return frozenset(), ()  # Execution reports the error against this cell.
    cites = citations(text)
    refs = frozenset(t for k, t in cites if k == "val")
    if tree is not None and isinstance(tree.body, ast.JoinedStr):
        refs |= analyze_code(source)[1]
    return refs, cites


@dataclass
class DependencyGraph:
    blocks: list[Block]
    order: list[str]                       # execution order
    producers: dict[str, str]              # name -> id of the last block defining it
    edges: dict[str, frozenset[str]]       # block id -> ids it depends on
    unresolved: dict[str, frozenset[str]]  # block id -> names nothing defines
    #: block id -> (name, id of the later block that defines it)
    early: dict[str, tuple[tuple[str, str], ...]] = field(default_factory=dict)

    def by_id(self, bid: str) -> Block:
        for b in self.blocks:
            if b.id == bid:
                return b
        raise KeyError(bid)

    def descendants(self, bid: str) -> set[str]:
        """Every block transitively depending on ``bid``."""
        rev: dict[str, set[str]] = {b.id: set() for b in self.blocks}
        for dst, srcs in self.edges.items():
            for s in srcs:
                if s in rev:
                    rev[s].add(dst)
        out: set[str] = set()
        stack = [bid]
        while stack:
            cur = stack.pop()
            for nxt in rev.get(cur, ()):
                if nxt not in out:
                    out.add(nxt)
                    stack.append(nxt)
        return out


def redefinitions(blocks: list[Block]) -> list[tuple[str, Block, Block]]:
    """``(name, first, again)`` for each name a second cell binds again.

    A calculation's value is printed where it is computed; if another cell
    rebinds the name, prose and tables built later show the other value and
    the document contradicts itself. Cells that only present -- tables, plots,
    drawings -- may share scratch names with each other and with the prelude.
    """
    first: dict[str, Block] = {}
    out = []
    for b in blocks:  # document order: the later cell is the one reported
        if not b.is_code:
            continue
        for name in sorted(b.defs):
            if name.startswith("_"):
                continue
            owner = first.get(name)
            if owner is None:
                first[name] = b
            elif _computes(owner) or _computes(b):
                out.append((name, owner, b))
    return out


def _computes(block: Block) -> bool:
    return block.kind not in PRESENTATION_KINDS and block.kind != "prelude"


def default_provided() -> frozenset[str]:
    """Names the kernel seeds into every document namespace.

    These resolve without creating an edge, so a star-import in the prelude
    does not make every unit and helper look undefined.
    """
    from kip import __all__

    return frozenset(__all__) | {"__file__", "__name__"}


def execution_order(blocks: list[Block]) -> list[Block]:
    """Calculations top to bottom, then presentation top to bottom."""
    first = [b for b in blocks if b.kind not in PRESENTATION_KINDS]
    return first + [b for b in blocks if b.kind in PRESENTATION_KINDS]


def analyze(
    blocks: list[Block], provided: frozenset[str] | None = None
) -> DependencyGraph:
    """Populate defs/refs/cites on each block and resolve its dependencies.

    ``provided`` are names the kernel seeds into the namespace before any block
    runs (unit names, bare math functions).  They resolve without an edge.
    """
    if provided is None:
        provided = default_provided()
    from .blocks import CONTENT_KINDS

    for b in blocks:
        if b.is_code:
            b.defs, b.refs = analyze_code(b.source)
            b.eager = eager_refs(b.source) & b.refs
            # An empty content cell places the object named by its id, so it
            # depends on whatever builds that object.
            if not b.source.strip() and b.kind in CONTENT_KINDS:
                b.refs = b.eager = frozenset({b.id})
            b.cites = ()
        else:
            refs, cites = analyze_text(b.source)
            b.defs, b.refs, b.cites = frozenset(), refs, cites
            b.eager = frozenset()  # a missing @val: renders as ?name?, with a warning

    ordered = execution_order(blocks)
    has_prelude = any(x.kind == "prelude" for x in blocks)
    producers: dict[str, str] = {}
    edges: dict[str, frozenset[str]] = {}
    unresolved: dict[str, frozenset[str]] = {}
    early: dict[str, tuple[tuple[str, str], ...]] = {}
    for i, b in enumerate(ordered):
        deps: set[str] = set()
        missing: set[str] = set()
        late: list[tuple[str, str]] = []
        for name in sorted(b.refs):
            owner = producers.get(name)
            if owner is None:
                later = next((x.id for x in ordered[i + 1:] if name in x.defs), None)
                if later is not None:
                    if name in b.eager:
                        late.append((name, later))
                    else:
                        deps.add(later)  # read when a function is called
                elif name not in provided and name not in b.defs:
                    missing.add(name)
            elif owner != b.id:
                deps.add(owner)
        if has_prelude and b.kind != "prelude":
            deps.add("__prelude__")
        edges[b.id] = frozenset(deps)
        unresolved[b.id] = frozenset(missing)
        early[b.id] = tuple(late)
        for name in b.defs:
            producers[name] = b.id

    return DependencyGraph(blocks, [b.id for b in ordered], producers, edges, unresolved, early)
