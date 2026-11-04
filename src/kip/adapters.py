"""Objects from other libraries that a cell may end with.

A draw cell shows a schemdraw drawing or a matplotlib figure; a table cell
shows a SKiDL circuit's bill of materials. Nothing here imports those
libraries until a cell hands kip one of their objects.
"""
from __future__ import annotations

import io
import re

__all__ = ["adapt", "from_matplotlib"]


def adapt(value, kind: str):
    """``value`` as the content a ``kind`` cell renders, if it comes from a library
    kip knows; otherwise ``value`` unchanged."""
    root = (type(value).__module__ or "").split(".")[0]
    if root == "schemdraw" and kind == "draw" and hasattr(value, "get_imagedata"):
        from .schematic import from_schemdraw
        return from_schemdraw(value)
    if root == "matplotlib" and kind == "draw":
        figure = value if hasattr(value, "savefig") else getattr(value, "figure", None)
        if figure is not None and hasattr(figure, "savefig"):
            return from_matplotlib(figure)
    if root == "skidl" and hasattr(value, "parts"):
        from .schematic import from_skidl
        return from_skidl(value).kip_content(kind)
    return value


def from_matplotlib(figure, *, width: float | None = None, caption: str | None = None):
    """A matplotlib figure as a vector :class:`~kip.Drawing` -- for the plots other
    libraries make (scikit-rf Smith charts, openEMS patterns, cocotb traces).

    Prefer :func:`kip.plot` for your own data: its axes match the document's.
    """
    from .content import Drawing
    buffer = io.BytesIO()
    figure.savefig(buffer, format="svg", bbox_inches="tight", transparent=True)
    svg = buffer.getvalue()
    m = re.search(rb"<svg[^>]*\bwidth=\"([\d.]+)pt\"", svg)
    natural = float(m.group(1)) * 25.4 / 72 if m else figure.get_size_inches()[0] * 25.4
    return Drawing(svg=svg, width=min(width, natural) if width else natural, caption=caption)
