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
