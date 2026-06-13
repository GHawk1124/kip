r"""AST lint for handcalcs-rendered blocks.

This is a **correctness** pass, not style.  handcalcs
renders several perfectly valid Python constructs *silently wrong* -- the
document compiles, looks plausible, and states false mathematics:

===========================  ==========================================
``y = x if c else z``        renders ``y = x``; the condition vanishes
``a, b = 3.0, 4.0``          renders ``a, b = 3.0, 4.0, 4.000 = ... = 3.000``
``y = q.to(MPa)``            renders ``\mathrm{q.to} \mathrm{MPa}``
``y = (expr).to(MPa)``       conversion silently dropped, or hard crash
===========================  ==========================================

Rejecting these is therefore mandatory.  Use ``result_unit=`` block metadata
instead of ``.to()``.
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


_BANNED_STMTS = {
    ast.For: ("loops", "handcalcs cannot render iteration; unroll it or compute in a prelude helper"),
    ast.AsyncFor: ("loops", "handcalcs cannot render iteration"),
    ast.While: ("loops", "handcalcs cannot render iteration"),
    ast.FunctionDef: ("function definitions", "define helpers in the prelude, above the first block marker"),
    ast.AsyncFunctionDef: ("function definitions", "define helpers in the prelude"),
    ast.ClassDef: ("class definitions", "define classes in the prelude"),
    ast.With: ("with statements", "not supported by handcalcs"),
    ast.Try: ("try statements", "not supported by handcalcs"),
}


def validate_block(block: Block, path: str | Path = "doc.py") -> list[Diagnostic]:
    """Return diagnostics for one block. Non-handcalcs blocks are not linted."""
    if not block.is_code or not block.source.strip():
        return []

    offset = block.body_start - 1
    out: list[Diagnostic] = []

    def err(node: ast.AST, msg: str, hint: str = "") -> None:
        out.append(Diagnostic("error", block.id, offset + getattr(node, "lineno", 1), msg, hint))

    def warn(node: ast.AST, msg: str, hint: str = "") -> None:
        out.append(Diagnostic("warning", block.id, offset + getattr(node, "lineno", 1), msg, hint))

    try:
        tree = ast.parse(block.source)
    except SyntaxError as e:
        return [Diagnostic("error", block.id, offset + (e.lineno or 1),
                           f"syntax error: {e.msg}")]

    if not block.uses_handcalcs:
        # prelude / symbolic / controlled / plot / table / draw / sources
        # blocks are ordinary Python, not subject to handcalcs' constraints
        return out

    for node in ast.walk(tree):
        for cls, (what, hint) in _BANNED_STMTS.items():
            if isinstance(node, cls):
                err(node, f"{what} are not supported in a kip.{block.kind} block", hint)

        if isinstance(node, ast.IfExp):
            err(node,
                "conditional expressions render INCORRECTLY (the condition is "
                "silently dropped from the output)",
                "use a real if/else statement, which handcalcs renders as "
                "'Since, x > y ->'")

        if isinstance(node, ast.Attribute):
            err(node,
                f"attribute access '.{node.attr}' renders incorrectly",
                "use result_unit= on the block marker instead of .to(), and "
                "import bare names in the prelude (from math import sqrt) "
                "rather than calling math.sqrt")

        if isinstance(node, ast.AugAssign):
            err(node, "augmented assignment (+=, *=, ...) is not rendered",
                "write the full expression: x = x + 1")

        if isinstance(node, ast.Assign):
            if len(node.targets) > 1:
                err(node, "chained assignment (a = b = ...) is not rendered",
                    "use one assignment per line")
            for tgt in node.targets:
                if isinstance(tgt, (ast.Tuple, ast.List)):
                    err(tgt,
                        "tuple/list unpacking renders INCORRECTLY "
                        "(values and results are interleaved wrongly)",
                        "assign each name on its own line")
                elif isinstance(tgt, ast.Name) and tgt.id.endswith("_"):
                    warn(tgt, f"name {tgt.id!r} renders with an empty subscript "
                              f"('{tgt.id[:-1]}_{{}}')",
                         "drop the trailing underscore")
    return out


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
