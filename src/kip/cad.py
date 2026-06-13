"""Optional build123d projections and planar DXF drawings (``kip[cad]``).

All PDF views are vector SVGs. DXF geometry stays in millimetres at 1:1;
``width`` changes only the size of the illustration in the document.
"""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from .content import Drawing


def load_build123d():
    """Import build123d, skipping unreadable Windows system-font files.

    Some Windows installations have non-SFNT files with .ttf extensions.
    build123d scans these even for models that contain no text. Restrict the
    filter to font-directory enumeration and always restore glob afterwards.
    """
    import glob
    import importlib
    import os
    import sys

    if "build123d" in sys.modules:
        return sys.modules["build123d"]
    if os.name != "nt":
        return importlib.import_module("build123d")
    from fontTools.ttLib import TTFont, TTCollection, TTLibError
    original = glob.glob

    def readable_fonts(pattern, *args, **kwargs):
        paths = original(pattern, *args, **kwargs)
        if "fonts" not in str(pattern).lower():
            return paths
        valid = []
        for path in paths:
            try:
                font = (TTCollection if path.lower().endswith(".ttc") else TTFont)(path)
                font.close()
                valid.append(path)
            except (OSError, TTLibError):
                continue
        return valid

    glob.glob = readable_fonts
    try:
        return importlib.import_module("build123d")
    finally:
        glob.glob = original


def _drawing(visible, hidden=(), *, width=70, caption=None, dxf=None):
    bd = load_build123d()
    if dxf is not None and (Path(dxf).name != dxf or not dxf.lower().endswith(".dxf")):
        raise ValueError("dxf must be a .dxf filename without a directory")
    with TemporaryDirectory(prefix="kip-cad-") as tmp:
        root = Path(tmp)
        svg = bd.ExportSVG(unit=bd.Unit.MM, margin=1)
        svg.add_layer("visible", line_weight=0.35)
        svg.add_shape(visible, layer="visible")
        if hidden:
            svg.add_layer("hidden", line_color=(100, 100, 100),
                          line_type=bd.LineType.ISO_DASH_SPACE, line_weight=0.2)
            svg.add_shape(hidden, layer="hidden")
        svg.write(root / "view.svg")
        attachments = {}
        if dxf:
            exporter = bd.ExportDXF(unit=bd.Unit.MM)
            exporter.add_layer("outline", line_weight=0.35)
            exporter.add_shape(visible, layer="outline")
            exporter.write(root / dxf)
            attachments[dxf] = (root / dxf).read_bytes()
        return Drawing(svg=(root / "view.svg").read_bytes(), width=width, height=55,
                       caption=caption, attachments=attachments)


def cad_view(shape, view="iso", *, width=70, caption=None):
    """Project solid edges; hidden edges are dashed. Z is up in the model."""
    directions = {
        "iso": ((1, -1, 1), (0, 0, 1)),
        "top": ((0, 0, 1), (0, 1, 0)),
        "side": ((1, 0, 0), (0, 0, 1)),
        "front": ((0, -1, 0), (0, 0, 1)),
        "bottom": ((0, 0, -1), (0, -1, 0)),
    }
    if view not in directions:
        raise ValueError(f"unknown CAD view {view!r}; choose {', '.join(directions)}")
    bd = load_build123d()
    direction, up = directions[view]
    center = shape.bounding_box().center()
    distance = max(shape.bounding_box().size) * 10
    visible, hidden = shape.project_to_viewport(
        viewport_origin=center + bd.Vector(direction) * distance,
        viewport_up=up, look_at=center)
    return _drawing(visible, hidden, width=width, caption=caption)


def cad_section(shape, plane, *, dxf, width=70, caption=None):
    """Intersect the solid with a plane and export in that plane's XY frame."""
    bd = load_build123d()
    cut = bd.section(shape, section_by=plane)
    if not cut.edges():
        raise ValueError("section plane does not intersect the solid")
    return _drawing(plane.to_local_coords(cut), dxf=dxf, width=width, caption=caption)


def cad_face(face, *, dxf, width=70, caption=None):
    """Export one planar face, including inner wires, in its local XY frame."""
    bd = load_build123d()
    plane = bd.Plane(face)
    return _drawing(plane.to_local_coords(face), dxf=dxf, width=width, caption=caption)
