"""A small SVG canvas in millimetres, sized to what is drawn on it.

The electronics readers draw schematics, boards, timing diagrams, Smith charts
and layouts with it, so they share one look: kip's ink and paper colours,
DejaVu Sans Mono for the technical text and Libertinus Serif for legends --
fonts Typst always has, so a drawing renders the same everywhere.
"""
from __future__ import annotations

import math

__all__ = ["Canvas", "INK", "FAINT", "PAPER", "RULE", "MONO", "SERIF", "escape"]

INK = "#17140f"
FAINT = "#6d6455"
RULE = "#b3a488"
PAPER = "#f7f2e3"
MONO = "DejaVu Sans Mono"
SERIF = "Libertinus Serif"

#: Average advance of a character, as a fraction of the font size.
_ADVANCE = {MONO: 0.602, SERIF: 0.5}


def escape(text) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace("'", "&#39;").replace('"', "&quot;"))


def _n(value: float) -> str:
    text = f"{value:.3f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def text_width(text: str, size: float, font: str = MONO) -> float:
    return len(str(text)) * size * _ADVANCE.get(font, 0.55)


class Canvas:
    """SVG elements in millimetres; :meth:`svg` sizes the page to their extent."""

    def __init__(self) -> None:
        self.parts: list[str] = []
        self.defs: list[str] = []
        self.bounds = [math.inf, math.inf, -math.inf, -math.inf]

    def __len__(self) -> int:
        return len(self.parts)

    @property
    def empty(self) -> bool:
        return not self.parts

    def grow(self, xs, ys, pad: float = 0.0) -> None:
        b = self.bounds
        b[0] = min(b[0], min(xs) - pad)
        b[1] = min(b[1], min(ys) - pad)
        b[2] = max(b[2], max(xs) + pad)
        b[3] = max(b[3], max(ys) + pad)

    @staticmethod
    def _style(stroke, width, fill, dash=None, opacity=None, cap="round", join="round") -> str:
        out = [f"fill='{fill or 'none'}'"]
        if stroke:
            out.append(f"stroke='{stroke}' stroke-width='{_n(width)}' stroke-linecap='{cap}' "
                       f"stroke-linejoin='{join}'")
            if dash:
                out.append(f"stroke-dasharray='{' '.join(_n(d) for d in dash)}'")
        if opacity is not None:
            out.append(f"opacity='{_n(opacity)}'")
        return " ".join(out)

    def line(self, x1, y1, x2, y2, *, stroke=INK, width=0.25, dash=None, cap="round", opacity=None):
        self.parts.append(f"<line x1='{_n(x1)}' y1='{_n(y1)}' x2='{_n(x2)}' y2='{_n(y2)}' "
                          + self._style(stroke, width, None, dash, opacity, cap) + "/>")
        self.grow((x1, x2), (y1, y2), width / 2)

    def polyline(self, points, *, stroke=INK, width=0.25, fill=None, closed=False, dash=None,
                 opacity=None, cap="round"):
        points = list(points)
        if len(points) < 2:
            return
        tag = "polygon" if closed else "polyline"
        coords = " ".join(f"{_n(x)},{_n(y)}" for x, y in points)
        self.parts.append(f"<{tag} points='{coords}' "
                          + self._style(stroke, width, fill, dash, opacity, cap) + "/>")
        xs, ys = zip(*points)
        self.grow(xs, ys, width / 2 if stroke else 0)

    def rect(self, x, y, w, h, *, stroke=None, width=0.25, fill=None, rx=0.0, dash=None, opacity=None):
        x, w = (x + w, -w) if w < 0 else (x, w)
        y, h = (y + h, -h) if h < 0 else (y, h)
        radius = f" rx='{_n(rx)}'" if rx else ""
        self.parts.append(f"<rect x='{_n(x)}' y='{_n(y)}' width='{_n(w)}' height='{_n(h)}'{radius} "
                          + self._style(stroke, width, fill, dash, opacity) + "/>")
        self.grow((x, x + w), (y, y + h), width / 2 if stroke else 0)

    def circle(self, cx, cy, r, *, stroke=None, width=0.25, fill=None, opacity=None, dash=None):
        self.parts.append(f"<circle cx='{_n(cx)}' cy='{_n(cy)}' r='{_n(r)}' "
                          + self._style(stroke, width, fill, dash, opacity) + "/>")
        self.grow((cx - r, cx + r), (cy - r, cy + r), width / 2 if stroke else 0)

    def path(self, d: str, points, *, stroke=INK, width=0.25, fill=None, dash=None, opacity=None,
             evenodd=False, cap="round"):
        """A path ``d``; ``points`` are coordinates that bound it."""
        rule = " fill-rule='evenodd'" if evenodd else ""
        self.parts.append(f"<path d='{d}'{rule} "
                          + self._style(stroke, width, fill, dash, opacity, cap) + "/>")
        points = list(points)
        if points:
            xs, ys = zip(*points)
            self.grow(xs, ys, width / 2 if stroke else 0)

    def arc(self, cx, cy, r, start, end, *, stroke=INK, width=0.25, dash=None):
        """An arc of a circle from ``start`` to ``end`` degrees, counter-clockwise on the page."""
        sweep = (end - start) % 360 or 360
        steps = max(2, int(sweep / 5) + 1)
        pts = [(cx + r * math.cos(math.radians(start + sweep * k / (steps - 1))),
                cy - r * math.sin(math.radians(start + sweep * k / (steps - 1)))) for k in range(steps)]
        self.polyline(pts, stroke=stroke, width=width, dash=dash)

    def text(self, x, y, text, *, size=2.0, anchor="start", middle=False, angle=0.0, font=MONO,
             fill=INK, weight=None, italic=False, opacity=None, stretch=1.0):
        """Text at (x, y): the baseline, or the centre line when ``middle``.

        ``angle`` turns it counter-clockwise on the page, about (x, y);
        ``stretch`` scales its width alone (0.8 sets it 20 % narrower).
        """
        text = str(text)
        if not text:
            return
        dy = 0.35 * size if middle else 0.0
        extra = ""
        if weight:
            extra += f" font-weight='{weight}'"
        if italic:
            extra += " font-style='italic'"
        if opacity is not None:
            extra += f" opacity='{_n(opacity)}'"
        steps = []
        if angle:
            steps.append(f"rotate({_n(-angle)} {_n(x)} {_n(y)})")
        if stretch != 1.0:
            steps.append(f"translate({_n(x)} {_n(y)}) scale({_n(stretch)} 1) translate({_n(-x)} {_n(-y)})")
        turn = f" transform='{' '.join(steps)}'" if steps else ""
        self.parts.append(f"<text x='{_n(x)}' y='{_n(y + dy)}' font-family='{font}' "
                          f"font-size='{_n(size)}' fill='{fill}' text-anchor='{anchor}'{extra}{turn}>"
                          f"{escape(text)}</text>")
        w = text_width(text, size, font) * stretch
        x0 = {"start": 0.0, "middle": -w / 2, "end": -w}[anchor]
        corners = [(x0, dy + 0.25 * size), (x0 + w, dy + 0.25 * size),
                   (x0, dy - 0.8 * size), (x0 + w, dy - 0.8 * size)]
        c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
        pts = [(x + px * c + py * s, y - px * s + py * c) for px, py in corners]
        xs, ys = zip(*pts)
        self.grow(xs, ys)

    def raw(self, markup: str, points) -> None:
        self.parts.append(markup)
        points = list(points)
        if points:
            xs, ys = zip(*points)
            self.grow(xs, ys)

    def svg(self, *, margin: float = 1.0, scale: float = 1.0, background: str | None = None,
            bounds=None) -> bytes:
        """The drawing as SVG bytes, ``scale`` millimetres on paper per unit drawn."""
        x0, y0, x1, y1 = bounds or self.bounds
        if not math.isfinite(x0):
            x0 = y0 = 0.0
            x1 = y1 = 1.0
        x0, y0, x1, y1 = x0 - margin, y0 - margin, x1 + margin, y1 + margin
        w, h = x1 - x0, y1 - y0
        ground = (f"<rect x='{_n(x0)}' y='{_n(y0)}' width='{_n(w)}' height='{_n(h)}' fill='{background}'/>"
                  if background else "")
        defs = f"<defs>{''.join(self.defs)}</defs>" if self.defs else ""
        return (f"<svg xmlns='http://www.w3.org/2000/svg' width='{_n(w * scale)}mm' "
                f"height='{_n(h * scale)}mm' viewBox='{_n(x0)} {_n(y0)} {_n(w)} {_n(h)}'>"
                + defs + ground + "".join(self.parts) + "</svg>").encode("utf-8")

    def size(self, margin: float = 1.0) -> tuple[float, float]:
        x0, y0, x1, y1 = self.bounds
        if not math.isfinite(x0):
            return 2 * margin, 2 * margin
        return x1 - x0 + 2 * margin, y1 - y0 + 2 * margin

    def drawing(self, *, width: float | None = None, caption=None, attachments=None, margin=1.0,
                scale: float = 1.0, background=None, enlarge: bool = False):
        """A :class:`kip.Drawing` of this canvas, at most ``width`` mm wide.

        ``enlarge`` draws it ``width`` wide even when that is larger than life:
        a 40 mm board is unreadable at its own size.
        """
        from .content import Drawing
        natural = self.size(margin)[0] * scale
        shown = (width if enlarge else min(width, natural)) if width else natural
        return Drawing(svg=self.svg(margin=margin, scale=scale, background=background),
                       width=shown, caption=caption, attachments=dict(attachments or {}))
