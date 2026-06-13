"""Static dependency analysis over blocks, and topological execution order.

Dependencies are derived by *reading* the code, never by running or tracing it
(marimo's rule): each block's ``defs`` are the global names it binds and its
``refs`` are the global names it reads without binding.  An edge ``A -> B``
exists when ``B.refs & A.defs`` is non-empty.  The result is a DAG; a cycle is
a hard error naming the blocks involved.
"""

from __future__ import annotations

import ast
import builtins
import re
from dataclasses import dataclass

from .blocks import Block

__all__ = [
    "analyze",
    "default_provided",
    "analyze_code",
    "analyze_text",
    "CITE_RE",
    "DependencyGraph",
    "CycleError",
]

_BUILTINS = frozenset(dir(builtins))

#: ``@val:name`` inlines a computed value; ``@blk:id``/``@req:ID`` cross-reference.
CITE_RE = re.compile(r"@(?P<kind>val|blk|req):(?P<target>[A-Za-z_][A-Za-z0-9_\-]*)")


class CycleError(Exception):
    """The document's blocks form a dependency cycle."""

    def __init__(self, cycle: list[str]):
        self.cycle = cycle
        super().__init__(
            "blocks form a dependency cycle: " + " -> ".join(cycle + [cycle[0]])
        )


class _ScopeVisitor(ast.NodeVisitor):
    """Collect module-level bindings and free (global) reads."""

    def __init__(self) -> None:
        self.defs: set[str] = set()
        self.loads: set[str] = set()
        self._local_stack: list[set[str]] = []

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
        for s in node.body:
            self.visit(s)
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
        self.visit(node.body)
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


def analyze_code(source: str) -> tuple[frozenset[str], frozenset[str]]:
    """Return ``(defs, refs)`` for a block of Python source."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return frozenset(), frozenset()
    v = _ScopeVisitor()
    for stmt in tree.body:
        v.visit(stmt)
    refs = {n for n in v.loads if n not in v.defs and n not in _BUILTINS}
    return frozenset(v.defs), frozenset(refs)


def analyze_text(source: str) -> tuple[frozenset[str], tuple[tuple[str, str], ...]]:
    """Return ``(refs, cites)`` for a prose block's ``@val:``/``@blk:``/``@req:``."""
    cites = tuple(
        (m.group("kind"), m.group("target")) for m in CITE_RE.finditer(source)
    )
    refs = frozenset(t for k, t in cites if k == "val")
    return refs, cites


@dataclass
class DependencyGraph:
    blocks: list[Block]
    order: list[str]
    producers: dict[str, str]              # name -> id of the block defining it
    edges: dict[str, frozenset[str]]       # block id -> ids it depends on
    unresolved: dict[str, frozenset[str]]  # block id -> names nothing defines

    def by_id(self, bid: str) -> Block:
        for b in self.blocks:
            if b.id == bid:
                return b
        raise KeyError(bid)

    def descendants(self, bid: str) -> set[str]:
        """Every block transitively depending on ``bid`` (for invalidation)."""
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


def default_provided() -> frozenset[str]:
    """Names the kernel seeds into every document namespace.

    These resolve without creating an edge, so a star-import in the prelude
    does not make every unit and helper look undefined.
    """
    from kip import __all__

    return frozenset(__all__)


def analyze(
    blocks: list[Block], provided: frozenset[str] | None = None
) -> DependencyGraph:
    """Populate defs/refs/cites on each block and compute execution order.

    ``provided`` are names the kernel seeds into the namespace before any block
    runs (unit names, bare math functions).  They resolve without an edge, so a
    star-import in the prelude does not make every unit look undefined.
    """
    if provided is None:
        provided = default_provided()
    for b in blocks:
        if b.is_code:
            b.defs, b.refs = analyze_code(b.source)
            b.cites = ()
        else:
            refs, cites = analyze_text(b.source)
            b.defs, b.refs, b.cites = frozenset(), refs, cites

    producers: dict[str, str] = {}
    for b in blocks:
        for name in b.defs:
            producers.setdefault(name, b.id)

    has_prelude = any(x.kind == "prelude" for x in blocks)
    edges: dict[str, frozenset[str]] = {}
    unresolved: dict[str, frozenset[str]] = {}
    for b in blocks:
        deps: set[str] = set()
        missing: set[str] = set()
        for name in b.refs:
            owner = producers.get(name)
            if owner is None:
                if name not in provided:
                    missing.add(name)
            elif owner != b.id:
                deps.add(owner)
        # the prelude supplies imports and unit names to everything
        if has_prelude and b.kind != "prelude":
            deps.add("__prelude__")
        edges[b.id] = frozenset(deps)
        unresolved[b.id] = frozenset(missing)

    order = _toposort(blocks, edges)
    return DependencyGraph(blocks, order, producers, edges, unresolved)


def _toposort(blocks: list[Block], edges: dict[str, frozenset[str]]) -> list[str]:
    """Kahn's algorithm, breaking ties by document order for stable output."""
    index = {b.id: i for i, b in enumerate(blocks)}
    indeg = {b.id: len(edges[b.id]) for b in blocks}
    ready = sorted([bid for bid, d in indeg.items() if d == 0], key=index.__getitem__)
    out: list[str] = []
    while ready:
        cur = ready.pop(0)
        out.append(cur)
        for b in blocks:
            if cur in edges[b.id]:
                indeg[b.id] -= 1
                if indeg[b.id] == 0:
                    ready.append(b.id)
        ready.sort(key=index.__getitem__)

    if len(out) != len(blocks):
        stuck = [b.id for b in blocks if b.id not in out]
        raise CycleError(_find_cycle(stuck, edges))
    return out


def _find_cycle(candidates: list[str], edges: dict[str, frozenset[str]]) -> list[str]:
    cand = set(candidates)
    path: list[str] = []
    seen: set[str] = set()

    def walk(node: str) -> list[str] | None:
        if node in path:
            return path[path.index(node):]
        if node in seen:
            return None
        seen.add(node)
        path.append(node)
        for dep in sorted(edges.get(node, ())):
            if dep in cand:
                found = walk(dep)
                if found:
                    return found
        path.pop()
        return None

    for c in candidates:
        cyc = walk(c)
        if cyc:
            return cyc
    return candidates
