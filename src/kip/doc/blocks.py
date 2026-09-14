"""Document blocks and their rendering metadata."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

__all__ = ["Block", "BlockKind", "KINDS", "CODE_KINDS", "HANDCALC_KINDS",
           "CONTENT_KINDS"]

BlockKind = str

#: Supported block kinds.
KINDS: tuple[str, ...] = (
    "prelude",   # implicit: imports and setup above the first marker
    "text",      # prose, with @val:/@blk:/@req:/@src: citations
    "given",     # input quantities -- rendered as marked INPUT
    "controlled",  # inputs read from requirements, shown with provenance
    "calc",      # arithmetic, rendered symbolic -> substituted -> result
    "calculation", # a decorated function defined in an analysis module
    "symbolic",  # sympy derivation, rendered via TypstPrinter
    "plot",      # a Figure, rendered as a vector lilaq diagram
    "table",     # a Table, rendered as a Typst table (+ optional xlsx export)
    "draw",      # a Drawing, rendered through CeTZ
    "sources",   # a Sources mapping, rendered as a reference list
    "requirements",  # a Requirements object: item tree + requirement listing
    "verify",    # verification calls, rendered as a pass/fail panel
)

#: Kinds whose body is executed as Python.
CODE_KINDS: frozenset[str] = frozenset({
    "prelude", "given", "calc", "calculation", "symbolic", "plot", "table", "draw", "sources",
    "requirements", "verify", "controlled",
})

#: Kinds that bind a rich-content object for the renderer to pick up.
CONTENT_KINDS: frozenset[str] = frozenset({
    "plot", "table", "draw", "sources", "requirements",
})

#: Kinds routed through handcalcs (and therefore subject to its constraints).
HANDCALC_KINDS: frozenset[str] = frozenset({"given", "calc"})


@dataclass
class Block:
    """One addressable region of ``doc.py``.

    ``body_start``/``body_end`` are 1-based inclusive line numbers of the block
    body in the source file.  Edits to this span preserve the rest of the source file.
    """

    id: str
    kind: BlockKind
    source: str
    marker_line: int
    body_start: int
    body_end: int
    meta: dict[str, str] = field(default_factory=dict)

    # Populated by graph.analyze()
    defs: frozenset[str] = frozenset()
    refs: frozenset[str] = frozenset()
    cites: tuple[tuple[str, str], ...] = ()

    @property
    def is_code(self) -> bool:
        return self.kind in CODE_KINDS

    @property
    def uses_handcalcs(self) -> bool:
        return self.kind in HANDCALC_KINDS

    @property
    def has_content(self) -> bool:
        return self.kind in CONTENT_KINDS

    @property
    def result_unit(self) -> str | None:
        """Raw ``result_unit=`` metadata, unparsed."""
        return self.meta.get("result_unit")

    @property
    def result_units(self) -> list[tuple[str | None, str]]:
        """Requested unit conversions as ``(name_or_None, unit)`` pairs.

        ``.to()`` inside a rendered line is unusable -- handcalcs
        drops it silently or crashes -- so conversions are block metadata.

        Two forms are accepted::

            result_unit=MPa                    # applies to the last assignment
            result_unit="I_xx=mm**4, c_out=mm" # explicit per-name mapping
        """
        raw = self.meta.get("result_unit")
        if not raw:
            return []
        out: list[tuple[str | None, str]] = []
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            if "=" in part:
                name, _, unit = part.partition("=")
                out.append((name.strip(), unit.strip()))
            else:
                out.append((None, part))
        return out

    @property
    def precision(self) -> int:
        return int(self.meta.get("precision", 3))

    def content_hash(self) -> str:
        """Stable hash of everything that affects this block's output."""
        h = hashlib.blake2b(digest_size=16)
        h.update(self.kind.encode())
        h.update(b"\0")
        h.update(self.source.encode())
        h.update(b"\0")
        for k in sorted(self.meta):
            h.update(f"{k}={self.meta[k]}\0".encode())
        return h.hexdigest()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Block {self.kind}:{self.id} L{self.body_start}-{self.body_end}>"
