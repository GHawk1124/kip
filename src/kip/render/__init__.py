"""Rendering: blocks -> Typst -> vector PDF."""

from .emitter import emit, emit_body, emit_debug
from .layout import Layout, PageSpec, Position, auto_layout
from .pdf import (
    BlockGeometry, block_geometry, block_heights, export_assets,
    compile_pdf, compile_svg, measure_heights, render,
)

__all__ = [
    "emit", "emit_body", "emit_debug",
    "Layout", "PageSpec", "Position", "auto_layout",
    "compile_pdf", "compile_svg", "render",
    "block_geometry", "block_heights", "BlockGeometry",
    "export_assets", "measure_heights",
]
