"""Compile vector documents and export their associated assets."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import typst

from ..doc.kernel import Document
from .emitter import emit
from .layout import Layout

__all__ = [
    "compile_pdf", "compile_svg", "block_geometry", "BlockGeometry",
    "render", "vendor_dir", "export_assets", "measure_heights",
    "PACKAGE_DIR", "FONT_DIR",
]

from ..resources import TYPST

PACKAGE_DIR = TYPST / "packages"
FONT_DIR = TYPST / "fonts"

#: Pinned so output is reproducible run to run.
FIXED_TIMESTAMP = 0


def vendor_dir() -> str | None:
    """Local ``@preview`` package root, if it has been vendored."""
    if PACKAGE_DIR.is_dir() and any(PACKAGE_DIR.iterdir()):
        return str(PACKAGE_DIR)
    return None


def _font_paths() -> list[str]:
    return [str(FONT_DIR)] if FONT_DIR.is_dir() and any(FONT_DIR.iterdir()) else []


def _common_kwargs() -> dict:
    kw: dict = {}
    pkg = vendor_dir()
    if pkg:
        kw["package_path"] = pkg
    fonts = _font_paths()
    if fonts:
        kw["font_paths"] = fonts
    return kw


def compile_pdf(
    files: dict[str, bytes], *, deterministic: bool = True
) -> bytes:
    """Compile a Typst project to PDF bytes."""
    kw = _common_kwargs()
    if deterministic:
        kw["timestamp"] = FIXED_TIMESTAMP
    return typst.compile(files, **kw)


def compile_svg(files: dict[str, bytes]) -> list[bytes]:
    """Compile to SVG; returns one SVG per page."""
    out = typst.compile(files, format="svg", **_common_kwargs())
    if isinstance(out, bytes):
        return [out]
    return list(out)


@dataclass
class BlockGeometry:
    """Where a block actually landed, in page-relative millimetres."""

    id: str
    kind: str
    page: int
    x: float
    y: float

    @property
    def key(self) -> tuple[int, float, float]:
        return (self.page, self.y, self.x)


def block_geometry(files: dict[str, bytes]) -> list[BlockGeometry]:
    """Recover block positions from a single Typst query."""
    raw = typst.query(files, "<kipblk>", field="value", **_common_kwargs())
    data = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
    out: list[BlockGeometry] = []
    for item in data:
        try:
            out.append(BlockGeometry(
                id=str(item["id"]), kind=str(item.get("kind", "")),
                page=int(item["page"]), x=float(item["x"]), y=float(item["y"]),
            ))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def block_heights(geoms: list[BlockGeometry], page_height: float) -> dict[str, float]:
    """Infer each block's height from the gap to the next block on its page."""
    heights: dict[str, float] = {}
    ordered = sorted(geoms, key=lambda g: g.key)
    for i, g in enumerate(ordered):
        nxt = ordered[i + 1] if i + 1 < len(ordered) else None
        if nxt is not None and nxt.page == g.page:
            heights[g.id] = max(2.0, nxt.y - g.y)
        else:
            heights[g.id] = max(2.0, page_height - g.y)
    return heights


def measure_heights(doc: Document, width_mm: float, *, layout: Layout | None = None) -> dict[str, float]:
    """Measure each block's rendered height at a given content width.

    Auto-layout needs heights *at the column width the blocks will occupy*: a
    block 20mm tall across a full page is far taller in a half-width column, so
    measuring a full-width render and applying it to a two-column grid makes
    every block overlap the next.  One throwaway compile on a tall, narrow page
    gives true heights for the target width.
    """
    from .layout import Layout, PageSpec

    from dataclasses import replace
    spec = layout.page if layout is not None else PageSpec()
    margin = spec.grid_step
    probe = Layout(
        page=replace(spec,
            width=width_mm + 2 * margin, height=6000.0, margin=margin,
            grid=False, columns=1, title=None, subtitle=None,
            marking=None, header_left=None, header_right=None, footer_left=None,
        ),
        width_hint=width_mm,
    )
    geoms = sorted(block_geometry(emit(doc, probe)), key=lambda g: g.key)
    heights: dict[str, float] = {}
    for i, g in enumerate(geoms):
        if g.id == "__end__":
            continue
        nxt = geoms[i + 1] if i + 1 < len(geoms) else None
        heights[g.id] = max(2.0, (nxt.y - g.y) if nxt else 10.0)
    return heights


def export_assets(doc: Document, out_dir: str | Path) -> dict[str, str]:
    """Write table workbooks and drawing attachments beside the PDF.

    Returns ``{block_id: relative href}`` so the emitter can put a clickable
    link under the rendered (possibly truncated) table. The workbook always
    holds the full data set even when the document shows only the first rows.
    """
    from ..content import Drawing, Table

    out_dir = Path(out_dir)
    hrefs: dict[str, str] = {}
    for block in doc.ordered_blocks():
        result = doc.results.get(block.id)
        content = getattr(result, "content", None) if result else None
        if isinstance(content, Drawing):
            if content.svg is not None:
                svg_path = out_dir / "drawings" / f"{block.id}.svg"
                svg_path.parent.mkdir(parents=True, exist_ok=True)
                svg_path.write_bytes(content.svg)
            for name, data in content.attachments.items():
                if Path(name).name != name:
                    raise ValueError("drawing attachments must be plain filenames")
                out_dir.mkdir(parents=True, exist_ok=True)
                (out_dir / name).write_bytes(data)
            continue
        if not isinstance(content, Table) or not content.xlsx:
            continue
        target = (out_dir / content.xlsx).resolve()
        if not target.is_relative_to(out_dir.resolve()):
            raise ValueError("workbook filename must stay inside the output directory")
        content.to_xlsx(target)
        hrefs[block.id] = content.xlsx
    return hrefs


def render(
    doc: Document,
    out_path: str | Path | None = None,
    *,
    layout: Layout | None = None,
    deterministic: bool = True,
    assets: bool = True,
) -> Path:
    """Write all artifacts inside ``output/`` beside the source document.

    ``out_path`` may name a PDF or subdirectory within that output folder.
    Absolute paths must also stay within it; artifacts cannot escape the
    document's output tree.
    """
    root = doc.path.resolve().parent / "output"
    if out_path is None:
        from ..authoring import Report
        out_path = next((v.output for v in doc.namespace.values() if isinstance(v, Report)), None)
    requested = Path(out_path) if out_path is not None else Path(f"{doc.path.resolve().parent.name or 'doc'}.pdf")
    p = (requested if requested.is_absolute() else root / requested).resolve()
    if not p.is_relative_to(root):
        raise ValueError("output path must be inside output/ beside doc.py")
    p.parent.mkdir(parents=True, exist_ok=True)
    hrefs = export_assets(doc, p.parent) if assets else {}
    doc.assets = hrefs
    files = emit(doc, layout, hrefs)
    pdf = compile_pdf(files, deterministic=deterministic)
    p.write_bytes(pdf)
    return p
