"""Optional page settings and block positions stored in layout.toml."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import math

import tomlkit

__all__ = ["Layout", "PageSpec", "Position", "auto_layout", "PAPER_SIZES"]

#: Separator between title-block-ish fields in the running head.
SEPARATOR = "  •  "

#: width, height in mm
PAPER_SIZES: dict[str, tuple[float, float]] = {
    "us-letter": (215.9, 279.4),
    "us-legal": (215.9, 355.6),
    "a4": (210.0, 297.0),
    "a3": (297.0, 420.0),
}


@dataclass
class PageSpec:
    title: str | None = None
    subtitle: str | None = None
    paper: str = "us-letter"
    width: float | None = None   # explicit page width in mm (overrides paper)
    height: float | None = None  # explicit page height in mm
    margin: float = 15.0
    grid: bool = True
    grid_step: float = 5.0
    frames: bool = False
    columns: int = 1
    gutter: float = 8.0
    font_size: float = 10.0

    #: Running head, left side. Defaults to the document title.
    header_left: str | None = None
    #: Running head, right side. Defaults to author / revision / date.
    header_right: str | None = None
    #: Footer, left side. Defaults to project / document number.
    footer_left: str | None = None
    #: Control or classification marking printed at the top and bottom of
    #: every page, e.g. "CUI", "Proprietary", "ITAR controlled".
    marking: str | None = None

    author: str | None = None
    project: str | None = None
    document: str | None = None     # document number
    revision: str | None = None
    date: str | None = None
    checker: str | None = None
    client: str | None = None
    #: Extra title-block rows, rendered after the standard ones.
    extra_fields: dict[str, str] = field(default_factory=dict)

    def __post_init__(self):
        if not math.isfinite(self.grid_step) or self.grid_step <= 0:
            raise ValueError("grid_step must be a finite positive size in mm")

    def title_fields(self) -> list[tuple[str, str]]:
        """Ordered (label, value) rows for the drawing-style title block."""
        rows = [
            ("project", self.project), ("document", self.document),
            ("client", self.client), ("author", self.author),
            ("checked", self.checker), ("rev", self.revision),
            ("date", self.date),
        ]
        out = [(k, v) for k, v in rows if v]
        out.extend((k, str(v)) for k, v in self.extra_fields.items())
        return out

    def resolved_header_left(self) -> str | None:
        return self.header_left if self.header_left is not None else self.title

    def resolved_header_right(self) -> str | None:
        if self.header_right is not None:
            return self.header_right
        bits = [b for b in (self.author,
                            f"Rev {self.revision}" if self.revision else None,
                            self.date) if b]
        return SEPARATOR.join(bits) if bits else None

    def resolved_footer_left(self) -> str | None:
        if self.footer_left is not None:
            return self.footer_left
        bits = [b for b in (self.project, self.document) if b]
        return SEPARATOR.join(bits) if bits else None

    @property
    def size(self) -> tuple[float, float]:
        if self.width is not None and self.height is not None:
            return (self.width, self.height)
        return PAPER_SIZES.get(self.paper, PAPER_SIZES["us-letter"])

    def snapped_margin(self) -> float:
        """Margin rounded to a whole number of grid cells.

        Content can only sit on the printed grid if the content origin is
        itself on it, so the margin is quantised rather than taken literally.
        """
        if not self.grid or self.grid_step <= 0:
            return self.margin
        cells = max(1, round(self.margin / self.grid_step))
        return cells * self.grid_step

    @property
    def content_width(self) -> float:
        return math.floor(self.size[0] / self.grid_step) * self.grid_step - 2 * self.snapped_margin()

    @property
    def content_height(self) -> float:
        return math.floor(self.size[1] / self.grid_step) * self.grid_step - 2 * max(self.snapped_margin(), 3 * self.grid_step)

    def column_width(self) -> float:
        if self.columns <= 1:
            return self.content_width
        total_gutter = self.gutter * (self.columns - 1)
        return (self.content_width - total_gutter) / self.columns


@dataclass
class Position:
    x: float
    y: float
    w: float
    page: int = 1
    pinned: bool = False


@dataclass
class Layout:
    """Positions for freeform mode; empty means flow mode."""

    page: PageSpec = field(default_factory=PageSpec)
    blocks: dict[str, Position] = field(default_factory=dict)
    path: Path | None = None
    #: Width (mm) blocks will occupy when no explicit position exists. The
    #: height probe sets this so it measures the same rendering the final
    #: document uses -- otherwise a calc measured wide but rendered stacked
    #: is three times taller than planned and overlaps the block below it.
    width_hint: float | None = None

    @property
    def freeform(self) -> bool:
        return bool(self.blocks)

    @property
    def position_count(self) -> int:
        return len(self.blocks)

    def position(self, block_id: str) -> Position | None:
        return self.blocks.get(block_id)

    # -- io --------------------------------------------------------------
    @classmethod
    def load(cls, path: str | Path) -> "Layout":
        p = Path(path)
        if not p.exists():
            return cls(path=p)
        doc = tomlkit.parse(p.read_text(encoding="utf-8"))
        return cls._from_toml(doc, p)

    @classmethod
    def loads(cls, text: str) -> "Layout":
        return cls._from_toml(tomlkit.parse(text), None)

    @classmethod
    def _from_toml(cls, doc, path: Path | None) -> "Layout":
        raw_page = dict(doc.get("page", {}) or {})
        spec = PageSpec(
            title=raw_page.get("title"),
            subtitle=raw_page.get("subtitle"),
            paper=str(raw_page.get("paper", "us-letter")),
            margin=float(_mm(raw_page.get("margin", 18))),
            grid=bool(raw_page.get("grid", True)),
            grid_step=float(_mm(raw_page.get("grid_step", 5))),
            frames=bool(raw_page.get("frames", False)),
            columns=int(raw_page.get("columns", 1)),
            gutter=float(_mm(raw_page.get("gutter", 8))),
            font_size=float(raw_page.get("font_size", 10)),
            header_left=raw_page.get("header_left"),
            header_right=raw_page.get("header_right"),
            footer_left=raw_page.get("footer_left"),
            marking=raw_page.get("marking"),
            author=raw_page.get("author"),
            project=raw_page.get("project"),
            document=raw_page.get("document"),
            revision=raw_page.get("revision"),
            date=raw_page.get("date"),
            checker=raw_page.get("checker"),
            client=raw_page.get("client"),
            extra_fields=dict(raw_page.get("extra_fields", {}) or {}),
        )
        blocks: dict[str, Position] = {}
        for bid, raw in (doc.get("block", {}) or {}).items():
            raw = dict(raw)
            if "x" not in raw or "y" not in raw:
                continue
            blocks[str(bid)] = Position(
                x=float(_mm(raw["x"])), y=float(_mm(raw["y"])),
                w=float(_mm(raw.get("w", spec.column_width()))),
                page=int(raw.get("page", 1)),
                pinned=bool(raw.get("pinned", False)),
            )
        return cls(page=spec, blocks=blocks, path=path)

    def dumps(self) -> str:
        doc = tomlkit.document()
        doc.add(tomlkit.comment("kip layout sidecar -- positions only."))
        doc.add(tomlkit.comment("Deleting this file reverts to flow layout."))

        page = tomlkit.table()
        for key, val in (
            ("title", self.page.title), ("subtitle", self.page.subtitle),
            ("paper", self.page.paper), ("margin", f"{self.page.margin:g}mm"),
            ("grid", self.page.grid), ("grid_step", f"{self.page.grid_step:g}mm"),
            ("frames", self.page.frames),
            ("columns", self.page.columns), ("gutter", f"{self.page.gutter:g}mm"),
            ("font_size", self.page.font_size),
            ("marking", self.page.marking),
            ("header_left", self.page.header_left),
            ("header_right", self.page.header_right),
            ("footer_left", self.page.footer_left),
            ("project", self.page.project), ("document", self.page.document),
            ("client", self.page.client), ("author", self.page.author),
            ("checker", self.page.checker), ("revision", self.page.revision),
            ("date", self.page.date),
        ):
            if val is not None:
                page[key] = val
        doc["page"] = page

        if self.blocks:
            holder = tomlkit.table(is_super_table=True)
            for bid, pos in self.blocks.items():
                t = tomlkit.table()
                t["page"] = pos.page
                t["x"] = f"{pos.x:g}mm"
                t["y"] = f"{pos.y:g}mm"
                t["w"] = f"{pos.w:g}mm"
                if pos.pinned:
                    t["pinned"] = True
                holder[bid] = t
            doc["block"] = holder
        return tomlkit.dumps(doc)

    def save(self, path: str | Path | None = None) -> Path:
        target = Path(path) if path else self.path
        if target is None:
            raise ValueError("Layout has no path; pass one explicitly")
        target.write_text(self.dumps(), encoding="utf-8")
        self.path = target
        return target


def _mm(value) -> float:
    """Accept ``12``, ``12.0`` or ``"12mm"``."""
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().lower()
    for suffix, factor in (("mm", 1.0), ("cm", 10.0), ("in", 25.4), ("pt", 25.4 / 72)):
        if s.endswith(suffix):
            return float(s[: -len(suffix)]) * factor
    return float(s)


def auto_layout(
    doc,
    layout: Layout | None = None,
    *,
    heights: dict[str, float] | None = None,
    columns: int | None = None,
) -> Layout:
    """Reflow non-pinned blocks into a snapped column grid.

    This is the "AI can line things up" path: an agent writes only ``doc.py``
    and calls this (or ``kip layout --auto``) to get a tidy two-column page
    without computing any coordinates itself.

    ``heights`` maps block id -> measured height in mm, normally obtained from
    a previous render via :func:`kip.render.pdf.block_geometry`.  Blocks with
    no measured height fall back to a nominal estimate.
    """
    layout = layout or Layout()
    if columns is not None:
        layout.page.columns = columns
    spec = layout.page
    heights = heights or {}

    col_w = spec.column_width()
    step = spec.grid_step
    n_cols = max(1, spec.columns)

    def snap(v: float) -> float:
        return round(v / step) * step

    # column cursors, in page-relative mm
    cursor = [0.0] * n_cols
    page_no = [1] * n_cols
    new: dict[str, Position] = {}

    for block in doc.ordered_blocks():
        existing = layout.blocks.get(block.id)
        if existing is not None and existing.pinned:
            new[block.id] = existing
            continue

        h = heights.get(block.id, _estimate_height(block, col_w))
        col = min(range(n_cols), key=lambda i: (page_no[i], cursor[i]))

        if cursor[col] + h > spec.content_height and cursor[col] > 0:
            page_no[col] += 1
            cursor[col] = 0.0

        x = spec.snapped_margin() + col * (col_w + spec.gutter)
        y = spec.snapped_margin() + cursor[col]
        new[block.id] = Position(x=snap(x), y=snap(y), w=col_w, page=page_no[col])
        cursor[col] = math.ceil((cursor[col] + h + step) / step) * step

    layout.blocks = new
    return layout


def _estimate_height(block, width_mm: float) -> float:
    """Rough height when nothing has been measured yet."""
    if block.kind == "text":
        chars_per_line = max(20, int(width_mm / 1.8))
        lines = max(1, len(block.source) // chars_per_line + block.source.count("\n"))
        return 4.0 + lines * 4.5
    if block.kind in ("calc", "given"):
        return 8.0 + max(1, len(block.source.strip().splitlines())) * 7.5
    if block.kind == "symbolic":
        return 16.0
    return 12.0
