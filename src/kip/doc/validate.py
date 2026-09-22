"""Static checks on calc and inputs cells, run before anything executes.

Calc cells are rendered from their own syntax, so they are held to the grammar
:func:`kip.math.calc.check_calc` can display faithfully: assignments,
arithmetic, bare function calls and if/else. Everything else is refused with a
hint instead of being rendered as algebra the code did not perform.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from .blocks import Block

__all__ = ["Diagnostic", "validate_block", "validate_all", "ValidationError"]


@dataclass(frozen=True)
class Diagnostic:
    severity: str  # "error" | "warning"
    block_id: str
    line: int      # absolute line in doc.py
    message: str
    hint: str = ""

    def format(self, path: str | Path = "doc.py") -> str:
        s = f"{path}:{self.line}: {self.severity}: [{self.block_id}] {self.message}"
        if self.hint:
            s += f"\n    hint: {self.hint}"
        return s


class ValidationError(Exception):
    """Raised when a document contains error-severity diagnostics."""

    def __init__(self, diagnostics: list[Diagnostic], path: str | Path = "doc.py"):
        self.diagnostics = diagnostics
        self.path = path
        super().__init__(
            f"{len(diagnostics)} error(s) in {path}:\n"
            + "\n".join(d.format(path) for d in diagnostics)
        )


def validate_block(block: Block, path: str | Path = "doc.py") -> list[Diagnostic]:
    """Return diagnostics for one block. Only calc and inputs cells are held to a grammar."""
    if not block.is_code or not block.source.strip():
        return []

    offset = block.body_start - 1
    try:
        tree = ast.parse(block.source)
    except SyntaxError as e:
        return [Diagnostic("error", block.id, offset + (e.lineno or 1),
                           f"syntax error: {e.msg}")]

    if not block.renders_math:
        # prelude / symbolic / controlled / plot / table / draw / sources
        # blocks are ordinary Python
        return []

    from ..math.calc import check_calc, is_external_call
    if block.kind == "calc" and is_external_call(tree):
        return []  # an @calculation validates its own equations
    return [Diagnostic("error", block.id, offset + getattr(node, "lineno", 1),
                       f"{message} in a {block.kind} cell", hint)
            for node, message, hint in check_calc(tree)]


def validate_all(blocks: list[Block], path: str | Path = "doc.py") -> list[Diagnostic]:
    """Validate every block; returns all diagnostics in document order."""
    diags: list[Diagnostic] = []
    for b in blocks:
        diags.extend(validate_block(b, path))
    return diags


def raise_for_errors(diags: list[Diagnostic], path: str | Path = "doc.py") -> None:
    errors = [d for d in diags if d.severity == "error"]
    if errors:
        raise ValidationError(errors, path)


# -- unit names read as variables ------------------------------------------------

def ambiguous_units() -> frozenset[str]:
    """Unit names that are also everyday engineering variables: A, F, H, L, g, m, s, ..."""
    from ..units import UNIT_NAMES
    return frozenset(name for name in UNIT_NAMES if len(name) == 1)


def _bound_anywhere(tree: ast.AST) -> set[str]:
    """Every name a cell binds, including function parameters and loop targets."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Load):
            names.add(node.id)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.alias):
            names.add((node.asname or node.name).split(".")[0])
    return names


def unit_misuse(tree: ast.AST, candidates: frozenset[str] | set[str],
                units: frozenset[str] | None = None) -> list[ast.Name]:
    """Reads of unit names that are not in a unit position.

    ``L`` is a litre, so ``P / (b * L)`` with no ``L`` defined silently
    divides by a volume. A unit name is accepted where only a unit makes
    sense: after a number (``2 * m``, ``9.81 * m / s**2``), inside a unit
    expression written that way (``kg / m**3``), or passed to a call
    (``x.to(m)``, ``Q(3, m)``). Anywhere else it is almost certainly a
    variable the author forgot to define.
    """
    if not candidates:
        return []
    units = _unit_names() if units is None else units
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node

    def is_unit(node) -> bool:
        if isinstance(node, ast.Name):
            return node.id in candidates or node.id in units
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
            return is_unit(node.left) and _is_number(node.right)
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Mult, ast.Div)):
            return is_unit(node.left) and is_unit(node.right)
        return False

    def is_quantity(node) -> bool:
        """A number, or a number followed by units: 2, 9.81 * m / s**2."""
        if _is_number(node):
            return True
        return (isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Mult, ast.Div))
                and is_quantity(node.left) and is_unit(node.right))

    def accepted(node) -> bool:
        top = node
        while top in parents and is_unit(parents[top]):
            top = parents[top]
        parent = parents.get(top)
        if isinstance(parent, ast.BinOp) and isinstance(parent.op, (ast.Mult, ast.Div)):
            return parent.right is top and is_quantity(parent.left)
        if isinstance(parent, (ast.Call, ast.keyword)):
            return getattr(parent, "func", None) is not top
        if isinstance(parent, (ast.Assign, ast.AnnAssign)):
            return True  # an alias: unit = m
        return False

    return [node for node in ast.walk(tree)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
            and node.id in candidates and not accepted(node)]


def _is_number(node) -> bool:
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        node = node.operand
    return isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) \
        and not isinstance(node.value, bool)


def _unit_names() -> frozenset[str]:
    from ..units import UNIT_NAMES
    return frozenset(UNIT_NAMES)


def misuse_message(name: str) -> tuple[str, str]:
    from ..units import UNIT_NAMES
    unit = UNIT_NAMES[name]
    return (f"{name!r} is not defined here, so it means the unit {unit} "
            f"({name} is a kip unit name)",
            f"define {name} before this cell, or use it as a unit: after a "
            f"number (2 * {name}) or in a call (.to({name}))")


def unit_diagnostics(blocks: list[Block]) -> list[Diagnostic]:
    """Unit names read as variables anywhere in the document."""
    defined: set[str] = set()
    trees = {}
    for b in blocks:
        if not b.is_code or not b.source.strip():
            continue
        try:
            trees[b.id] = ast.parse(b.source)
        except SyntaxError:
            continue
        defined |= _bound_anywhere(trees[b.id])
    candidates = ambiguous_units() - defined
    out: list[Diagnostic] = []
    for b in blocks:
        if b.id not in trees:
            continue
        for node in unit_misuse(trees[b.id], candidates):
            message, hint = misuse_message(node.id)
            out.append(Diagnostic("error", b.id, b.body_start - 1 + node.lineno, message, hint))
    return out
