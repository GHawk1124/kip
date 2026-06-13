"""Parse ``doc.py`` into blocks, and write block bodies back in place.

Marker syntax::

    # %% kip.<kind> id=<slug> [key=value ...]

Everything above the first marker is the implicit ``prelude`` block: the PEP 723
header, imports and setup.  It always executes first and is never rendered.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path

from .blocks import KINDS, Block

__all__ = ["MARKER_RE", "parse", "load", "replace_body", "KipSyntaxError"]

MARKER_RE = re.compile(
    r"^\s*#\s*%%\s+(?P<legacy>kip\.)?(?P<kind>[a-z_]+)\s*(?P<meta>.*?)\s*$"
)
_META_RE = re.compile(r"(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<val>\"[^\"]*\"|'[^']*'|\S+)")
_SLUG_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class KipSyntaxError(SyntaxError):
    """A malformed block marker, reported with a file:line the user can click."""

    def __init__(self, message: str, path: str | Path | None, line: int) -> None:
        super().__init__(message)
        self.path = str(path) if path else "<string>"
        self.lineno = line

    def __str__(self) -> str:
        return f"{self.path}:{self.lineno}: {self.args[0]}"


def _parse_meta(raw: str) -> dict[str, str]:
    meta: dict[str, str] = {}
    for m in _META_RE.finditer(raw):
        val = m.group("val")
        if val[:1] in {'"', "'"} and val[:1] == val[-1:]:
            val = val[1:-1]
        meta[m.group("key")] = val
    return meta


def _dedent_body(lines: list[str]) -> str:
    """Strip trailing blank lines; block bodies are always at column 0."""
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def parse(text: str, path: str | Path | None = None) -> list[Block]:
    """Split document source into blocks. Raises :class:`KipSyntaxError`."""
    lines = text.splitlines()
    marks: list[tuple[int, str, dict[str, str]]] = []

    for i, line in enumerate(lines):
        m = MARKER_RE.match(line)
        if not m:
            continue
        kind = m.group("kind")
        if m.group("legacy"):
            meta = _parse_meta(m.group("meta"))
        else:
            try:
                tokens = shlex.split(m.group("meta"))
                meta = {}
                positional = []
                for token in tokens:
                    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", token):
                        key, value = token.split("=", 1)
                        meta[key] = value
                    else:
                        positional.append(token)
                if positional:
                    meta.setdefault("id", positional[0])
                if len(positional) > 1:
                    meta.setdefault("label", positional[1])
                if len(positional) > 2:
                    raise ValueError('expected: kind id "Label" key=value')
            except ValueError as e:
                raise KipSyntaxError(str(e), path, i + 1) from e
        kind = {"inputs": "given", "equations": "symbolic",
                "drawing": "draw", "references": "sources"}.get(kind, kind)
        if "unit" in meta:
            if "result_unit" in meta:
                raise KipSyntaxError("use unit= or result_unit=, not both", path, i + 1)
            meta["result_unit"] = meta.pop("unit")
        if kind not in KINDS or kind == "prelude":
            raise KipSyntaxError(
                f"unknown block kind 'kip.{kind}'; expected one of "
                + ", ".join(f"kip.{k}" for k in KINDS if k != "prelude"),
                path, i + 1,
            )
        if "id" not in meta:
            raise KipSyntaxError(f"kip.{kind} block is missing 'id='", path, i + 1)
        if not _SLUG_RE.match(meta["id"]):
            raise KipSyntaxError(
                f"block id {meta['id']!r} must be a valid identifier "
                "(letters, digits, underscore; not starting with a digit)",
                path, i + 1,
            )
        marks.append((i, kind, meta))

    blocks: list[Block] = []
    seen: dict[str, int] = {}

    first = marks[0][0] if marks else len(lines)
    prelude_src = _dedent_body(lines[:first])
    if prelude_src.strip():
        blocks.append(
            Block(id="__prelude__", kind="prelude", source=prelude_src,
                  marker_line=0, body_start=1, body_end=first)
        )

    for n, (idx, kind, meta) in enumerate(marks):
        end = marks[n + 1][0] if n + 1 < len(marks) else len(lines)
        bid = meta.pop("id")
        if bid in seen:
            raise KipSyntaxError(
                f"duplicate block id {bid!r} (first defined at line {seen[bid]})",
                path, idx + 1,
            )
        seen[bid] = idx + 1
        body_lines = lines[idx + 1:end]
        source = _dedent_body(list(body_lines))
        blocks.append(
            Block(id=bid, kind=kind, source=source, marker_line=idx + 1,
                  body_start=idx + 2,
                  body_end=idx + 1 + max(len(source.splitlines()), 1),
                  meta=meta)
        )
    return blocks


def load(path: str | Path) -> list[Block]:
    p = Path(path)
    return parse(p.read_text(encoding="utf-8"), p)


def replace_body(text: str, block: Block, new_body: str) -> str:
    """Return ``text`` with one block's body swapped out, nothing else touched.

    Source outside the block span is preserved byte-for-byte.
    """
    lines = text.splitlines(keepends=True)
    start = block.body_start - 1
    end = block.body_end
    tail = lines[end:]
    new_lines = [l + "\n" for l in new_body.splitlines()]
    if not new_lines:
        new_lines = ["\n"]
    return "".join(lines[:start] + new_lines + tail)
