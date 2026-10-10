"""Chip layout: GDSII and Magic layouts, layer maps, and OpenLane's metrics.

- :func:`read_gds` reads a GDSII stream file -- what Magic, KLayout, OpenROAD
  and gdstk write -- into a :class:`Layout` of cells. A draw cell shows the top
  cell flattened, layer by layer, with a legend; ``layout.size`` and
  :meth:`Layout.layer_table` give its extent and the area on each layer.
- :func:`read_magic` reads a Magic layout (``.mag``) the same way.
- Layers are named and coloured from SkyWater's sky130 numbering by default,
  or from a KLayout layer-properties file (``layer_map="pdk.lyp"``) or a
  dictionary ``{(68, 20): ("met1", "#2e5fb8")}``.
- :func:`read_metrics` reads OpenLane/LibreLane's ``metrics.json`` or
  ``metrics.csv``: die area, cell count, worst slack, power, DRC errors.
"""
from __future__ import annotations

import math
import re
import struct
from pathlib import Path

from .svg import FAINT, INK, SERIF, Canvas
from .units import fmt_quantity, ureg

__all__ = ["Layout", "Cell", "read_gds", "read_magic", "read_metrics", "SKY130"]

#: SkyWater sky130 layers (GDS layer, datatype) -> (name, colour).
SKY130 = {
    (64, 20): ("nwell", "#b9d9a5"), (64, 18): ("dnwell", "#d6e8c4"), (65, 20): ("diff", "#3f9b52"),
    (65, 44): ("tap", "#2d6d3a"), (66, 20): ("poly", "#c0392b"), (66, 44): ("licon1", "#3a2a2a"),
    (67, 20): ("li1", "#9b59b6"), (67, 44): ("mcon", "#2b2140"), (68, 20): ("met1", "#2e5fb8"),
    (68, 44): ("via", "#14284f"), (69, 20): ("met2", "#d0517a"), (69, 44): ("via2", "#5a1f33"),
    (70, 20): ("met3", "#1aa3a3"), (70, 44): ("via3", "#0b4545"), (71, 20): ("met4", "#d8a31a"),
    (71, 44): ("via4", "#5e4709"), (72, 20): ("met5", "#7f8c8d"), (76, 20): ("pad", "#95a5a6"),
    (93, 44): ("nsdm", "#e7d7f1"), (94, 20): ("psdm", "#f1e1c9"), (95, 20): ("npc", "#f6c9c4"),
    (75, 20): ("hvi", "#e9e3b8"), (78, 44): ("hvtp", "#efe6c1"), (125, 44): ("hvntm", "#e9dbf2"),
    (235, 4): ("prBoundary", "#9a8f7a"), (81, 4): ("areaid.sc", "#d9d2c0"),
}
#: Drawn below everything else, and unfilled: boundaries and implant layers.
_OUTLINE_ONLY = {"prBoundary", "areaid.sc", "nsdm", "psdm", "npc", "hvi", "hvtp", "hvntm", "dnwell"}

_PALETTE = ("#2e5fb8", "#c0392b", "#2c9a63", "#d8a31a", "#8e44ad", "#1aa3a3", "#d35400", "#7f8c8d",
            "#d0517a", "#3f9b52")

# -- GDSII ----------------------------------------------------------------------------


def _real8(data: bytes) -> float:
    if not any(data):
        return 0.0
    sign = -1.0 if data[0] & 0x80 else 1.0
    exponent = (data[0] & 0x7F) - 64
    mantissa = int.from_bytes(data[1:8], "big") / float(1 << 56)
    return sign * mantissa * 16.0 ** exponent


class Cell:
    """One GDS structure: its polygons, paths, labels and references to other cells."""

    def __init__(self, name: str):
        self.name = name
        self.polygons: list[tuple[int, int, list]] = []      # layer, datatype, points
        self.paths: list[tuple[int, int, float, list, int]] = []  # layer, datatype, width, points, type
        self.texts: list[tuple[int, int, float, float, str]] = []
        self.refs: list[tuple[str, tuple]] = []                 # cell name, 2x3 affine transform

    def __repr__(self) -> str:
        return f"<Cell {self.name}: {len(self.polygons)} polygons, {len(self.refs)} references>"


def _affine(x, y, angle=0.0, mag=1.0, reflect=False):
    c, s = math.cos(math.radians(angle)) * mag, math.sin(math.radians(angle)) * mag
    r = -1.0 if reflect else 1.0
    # x' = c*x - s*(r*y) + x0 ; y' = s*x + c*(r*y) + y0
    return (c, -s * r, x, s, c * r, y)


def _compose(a, b):
    """The transform applying ``b`` first, then ``a``."""
    return (a[0] * b[0] + a[1] * b[3], a[0] * b[1] + a[1] * b[4], a[0] * b[2] + a[1] * b[5] + a[2],
            a[3] * b[0] + a[4] * b[3], a[3] * b[1] + a[4] * b[4], a[3] * b[2] + a[4] * b[5] + a[5])


def _apply(t, points):
    return [(t[0] * x + t[1] * y + t[2], t[3] * x + t[4] * y + t[5]) for x, y in points]


_IDENTITY = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0)


class Layout:
    """A chip layout: cells, the references between them, and layer names and colours.

    ``layout.top`` is the top cell; ``layout.size`` its width and height;
    ``layout.layers`` the (layer, datatype) pairs it uses.
    """

    def __init__(self, cells: dict[str, Cell], *, unit: float = 1e-9, name: str = "", path: Path | None = None,
                 layer_map=None, source: str = "gds"):
        self.cells, self.unit, self.name, self.path, self.source = cells, unit, name, path, source
        self.layer_map = _layer_map(layer_map)

    @property
    def top_cells(self) -> list[str]:
        used = {ref for c in self.cells.values() for ref, _ in c.refs}
        tops = [n for n in self.cells if n not in used]
        return tops or list(self.cells)[:1]

    @property
    def top(self) -> Cell:
        tops = self.top_cells
        return self.cells[max(tops, key=lambda n: self._weight(n))]

    def _weight(self, name: str, seen=None) -> int:
        seen = seen or set()
        if name in seen or name not in self.cells:
            return 0
        seen.add(name)
        c = self.cells[name]
        return len(c.polygons) + len(c.paths) + sum(self._weight(r, seen) for r, _ in c.refs)

    def cell(self, name: str | None = None) -> Cell:
        if name is None:
            return self.top
        try:
            return self.cells[name]
        except KeyError:
            raise KeyError(f"no cell {name!r}; the top cells are {', '.join(self.top_cells)}") from None

    def flatten(self, cell: str | None = None, *, limit: int = 2_000_000):
        """Every shape of ``cell`` and its children, in database units:
        (layer, datatype, points, path width or None)."""
        out = []

        def walk(c: Cell, t, depth):
            if depth > 64:
                return
            for layer, dt, pts in c.polygons:
                out.append((layer, dt, _apply(t, pts), None))
            for layer, dt, width, pts, _ in c.paths:
                scale = math.hypot(t[0], t[3])
                out.append((layer, dt, _apply(t, pts), width * scale))
            if len(out) > limit:
                raise ValueError(f"cell {c.name} flattens to more than {limit} shapes; "
                                 "draw a smaller cell, or raise limit")
            for name, ref in c.refs:
                child = self.cells.get(name)
                if child is not None:
                    walk(child, _compose(t, ref), depth + 1)

        walk(self.cell(cell), _IDENTITY, 0)
        return out

    def _um(self, value):
        return ureg.Quantity(round(value * self.unit * 1e6, 6), "um")

    def bbox(self, cell: str | None = None):
        shapes = self.flatten(cell)
        xs = [x for *_, pts, _ in shapes for x, _ in pts]
        ys = [y for *_, pts, _ in shapes for _, y in pts]
        if not xs:
            return 0, 0, 0, 0
        return min(xs), min(ys), max(xs), max(ys)

    @property
    def size(self) -> tuple:
        x0, y0, x1, y1 = self.bbox()
        return self._um(x1 - x0), self._um(y1 - y0)

    @property
    def area(self):
        w, h = self.size
        return (w * h).to("um**2")

    @property
    def layers(self) -> list[tuple[int, int]]:
        return sorted({(l, d) for l, d, *_ in self.flatten()})

    def layer_name(self, key) -> str:
        entry = self.layer_map.get(key)
        return entry[0] if entry else f"{key[0]}/{key[1]}"

    def layer_table(self, cell: str | None = None, **options):
        """Each layer: its name, number, shape count, and drawn area (overlaps counted twice)."""
        from .content import Column, Table
        counts: dict = {}
        for layer, dt, pts, width in self.flatten(cell):
            n, a = counts.get((layer, dt), (0, 0.0))
            if width is None:
                area = abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]))) / 2
            else:
                area = width * sum(math.dist(p, q) for p, q in zip(pts, pts[1:]))
            counts[(layer, dt)] = (n + 1, a + area)
        named = all(isinstance(k[0], str) for k in counts)  # Magic names its layers; GDS numbers them
        rows = [(self.layer_name(k), *(() if named else (f"{k[0]}/{k[1]}",)), n,
                 round(a * (self.unit * 1e6) ** 2, 3))
                for k, (n, a) in sorted(counts.items(), key=lambda kv: (_rank(kv[0]), kv[0]))]
        columns = [Column("name", "Layer"), Column("gds", "GDS"), Column("shapes", "Shapes"),
                   Column("area", "Area (µm²)")]
        return Table([c for c in columns if not (named and c.key == "gds")], rows, **options)

    def drawing(self, cell: str | None = None, *, layers=None, width: float = 170, caption: str | None = None,
                legend: bool = True, attach: bool = False):
        """The cell flattened and drawn layer by layer, lowest layer first.

        ``layers`` picks which, by name (``["met1", "met2"]``) or number (``(68, 20)``).
        """
        shapes = self.flatten(cell)
        keys = sorted({(l, d) for l, d, *_ in shapes})
        if layers is not None:
            wanted = set()
            for item in layers:
                if isinstance(item, str):
                    matches = [k for k in keys if self.layer_name(k) == item]
                    if not matches:
                        raise KeyError(f"no layer {item!r} in this cell; it has "
                                       f"{', '.join(self.layer_name(k) for k in keys)}")
                    wanted.update(matches)
                else:
                    wanted.add(tuple(item) if len(item) == 2 else (item[0], 0))
            keys = [k for k in keys if k in wanted]
        x0, y0, x1, y1 = self.bbox(cell)
        span = max(x1 - x0, y1 - y0) or 1
        scale = 150.0 / span  # drawn 150 mm across, then fitted to the column
        canvas = Canvas()
        canvas.rect(0, 0, (x1 - x0) * scale, (y1 - y0) * scale, fill="#fdfbf4")
        colours = {}
        order = sorted(keys, key=lambda k: (self.layer_name(k) not in _OUTLINE_ONLY, _rank(k), k))
        by_layer: dict = {}
        for layer, dt, pts, w in shapes:
            by_layer.setdefault((layer, dt), []).append((pts, w))
        for n, key in enumerate(order):
            name = self.layer_name(key)
            colour = self.layer_map.get(key, (None, _PALETTE[n % len(_PALETTE)]))[1]
            colours[key] = colour
            outline = name in _OUTLINE_ONLY
            d_parts, strokes = [], []
            for pts, w in by_layer.get(key, []):
                q = [((x - x0) * scale, (y1 - y) * scale) for x, y in pts]
                if w is None:
                    d_parts.append("M" + "L".join(f"{x:.3f} {y:.3f}" for x, y in q) + "Z")
                else:
                    strokes.append((q, w * scale))
            if d_parts:
                if outline:
                    canvas.raw(f"<path d='{''.join(d_parts)}' fill='none' stroke='{colour}' stroke-width='0.15' "
                               f"stroke-dasharray='0.8 0.5'/>", [])
                else:
                    canvas.raw(f"<path d='{''.join(d_parts)}' fill='{colour}' fill-opacity='0.55' "
                               f"stroke='{colour}' stroke-width='0.06'/>", [])
            for q, w in strokes:
                canvas.polyline(q, stroke=colour, width=max(w, 0.05), opacity=0.55, cap="square")
        top = self.cell(cell)
        for layer, dt, x, y, text in top.texts:
            if (layer, dt) in colours or layers is None:
                canvas.text((x - x0) * scale, (y1 - y) * scale, text, size=2.2, anchor="middle", middle=True,
                            fill=INK)
        w_mm, h_mm = (x1 - x0) * scale, (y1 - y0) * scale
        if legend:
            lx, ly = 0.0, h_mm + 5.0
            for key in order:
                name = self.layer_name(key)
                step = 3.2 + 1.4 * len(name) + 4
                if lx > 0 and lx + step > max(w_mm, 80):
                    lx, ly = 0.0, ly + 4.2
                canvas.rect(lx, ly - 2.1, 2.4, 2.4, fill=colours[key], rx=0.3,
                            opacity=0.5 if name in _OUTLINE_ONLY else 0.8)
                canvas.text(lx + 3.2, ly, name, size=2.8, fill="#3a342b", font=SERIF)
                lx += step
        sw, sh = self.size if cell is None else (self._um(x1 - x0), self._um(y1 - y0))
        canvas.text(0, -2.0, f"{top.name}: {fmt_quantity(sw)} × {fmt_quantity(sh)}", size=2.4, fill=FAINT,
                    font=SERIF)
        attachments = {self.path.name: self.path.read_bytes()} if attach and self.path else {}
        return canvas.drawing(width=width, caption=caption, attachments=attachments, margin=1.0)

    def kip_content(self, kind: str):
        if kind == "draw":
            return self.drawing()
        if kind == "table":
            return self.layer_table()
        return self

    def kip_summary(self) -> str:
        w, h = self.size
        return (f"{self.source} layout {self.name}: top cell {self.top.name}, {len(self.cells)} cells, "
                f"{fmt_quantity(w)} × {fmt_quantity(h)}")


_STACK = [r"well", r"diff|tap|nsd|psd|mvn|mvp|subdiff", r"^(poly|p)$|polysilicon|gate", r"cont|^licon|^pc$|^ndc|^pdc",
          r"^(locali|li|li1)$", r"^(viali|mcon)$", r"^(metal1|m1)$", r"^(via1?|v1|m2c)$", r"^(metal2|m2)$",
          r"^(via2|v2|m3c)$", r"^(metal3|m3)$", r"^(via3|v3)$", r"^(metal4|m4)$", r"^(via4|v4)$", r"^(metal5|m5)$"]


def _rank(key) -> int:
    """Where a named (Magic) layer sits in the stack, so it is drawn in order."""
    name = key[0] if isinstance(key, tuple) else key
    if not isinstance(name, str):
        return 0
    return next((k for k, pattern in enumerate(_STACK) if re.search(pattern, name)), len(_STACK))


def read_gds(path, *, layer_map="sky130") -> Layout:
    """A GDSII stream file (``.gds``, ``.gds2``, ``.gdsii``; gzip too)."""
    import gzip
    from .authoring import project_path
    path = project_path(path)
    data = path.read_bytes()
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    cells: dict[str, Cell] = {}
    unit = 1e-9
    i, n = 0, len(data)
    cell: Cell | None = None
    element: dict = {}
    while i + 4 <= n:
        length, rtype, dtype = struct.unpack(">HBB", data[i:i + 4])
        if length < 4:
            break
        body = data[i + 4:i + length]
        i += length
        if rtype == 0x03:  # UNITS: user units per database unit, metres per database unit
            unit = _real8(body[8:16])
        elif rtype == 0x05:  # BGNSTR
            cell = None
        elif rtype == 0x06:  # STRNAME
            name = body.rstrip(b"\x00").decode("ascii", errors="replace")
            cell = cells.setdefault(name, Cell(name))
        elif rtype in (0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x2D):  # BOUNDARY PATH SREF AREF TEXT BOX
            element = {"kind": rtype, "layer": 0, "dt": 0, "width": 0, "pathtype": 0, "angle": 0.0, "mag": 1.0,
                       "reflect": False}
        elif rtype == 0x0D:
            element["layer"] = struct.unpack(">h", body[:2])[0]
        elif rtype in (0x0E, 0x16, 0x2E):  # DATATYPE TEXTTYPE BOXTYPE
            element["dt"] = struct.unpack(">h", body[:2])[0]
        elif rtype == 0x0F:
            element["width"] = abs(struct.unpack(">i", body[:4])[0])
        elif rtype == 0x21:
            element["pathtype"] = struct.unpack(">h", body[:2])[0]
        elif rtype == 0x10:  # XY
            values = struct.unpack(f">{len(body) // 4}i", body)
            element["xy"] = list(zip(values[0::2], values[1::2]))
        elif rtype == 0x12:  # SNAME
            element["sname"] = body.rstrip(b"\x00").decode("ascii", errors="replace")
        elif rtype == 0x13:  # COLROW
            element["colrow"] = struct.unpack(">hh", body[:4])
        elif rtype == 0x1A:  # STRANS
            element["reflect"] = bool(body[0] & 0x80)
        elif rtype == 0x1B:
            element["mag"] = _real8(body[:8])
        elif rtype == 0x1C:
            element["angle"] = _real8(body[:8])
        elif rtype == 0x19:  # STRING
            element["string"] = body.rstrip(b"\x00").decode("ascii", errors="replace")
        elif rtype == 0x11 and cell is not None and element:  # ENDEL
            kind, xy = element["kind"], element.get("xy", [])
            if kind in (0x08, 0x2D) and xy:
                pts = xy[:-1] if len(xy) > 1 and xy[0] == xy[-1] else xy
                cell.polygons.append((element["layer"], element["dt"], pts))
            elif kind == 0x09 and xy:
                width = element["width"]
                if element["pathtype"] == 2 and len(xy) > 1:  # square ends, extended half a width
                    xy = _extend(xy, width / 2)
                cell.paths.append((element["layer"], element["dt"], width, xy, element["pathtype"]))
            elif kind == 0x0A and xy:
                cell.refs.append((element["sname"], _affine(xy[0][0], xy[0][1], element["angle"], element["mag"],
                                                            element["reflect"])))
            elif kind == 0x0B and len(xy) >= 3:
                cols, rows = element.get("colrow", (1, 1))
                (ox, oy), (cx, cy), (rx, ry) = xy[:3]
                dcx, dcy = (cx - ox) / max(cols, 1), (cy - oy) / max(cols, 1)
                drx, dry = (rx - ox) / max(rows, 1), (ry - oy) / max(rows, 1)
                for c in range(cols):
                    for r in range(rows):
                        cell.refs.append((element["sname"], _affine(ox + c * dcx + r * drx, oy + c * dcy + r * dry,
                                                                    element["angle"], element["mag"],
                                                                    element["reflect"])))
            elif kind == 0x0C and xy:
                cell.texts.append((element["layer"], element["dt"], xy[0][0], xy[0][1], element.get("string", "")))
            element = {}
        elif rtype == 0x04:  # ENDLIB
            break
    if not cells:
        raise ValueError(f"{path.name}: no cells (is it a GDSII file?)")
    return Layout(cells, unit=unit, name=path.stem, path=path, layer_map=layer_map)


def _extend(points, d):
    def push(p, q):
        length = math.dist(p, q) or 1.0
        return (p[0] + (p[0] - q[0]) / length * d, p[1] + (p[1] - q[1]) / length * d)
    pts = list(points)
    pts[0] = push(pts[0], pts[1])
    pts[-1] = push(pts[-1], pts[-2])
    return pts

# -- layer maps -----------------------------------------------------------------------


def _layer_map(spec) -> dict:
    if spec is None or spec == "sky130":
        return dict(SKY130)
    if isinstance(spec, dict):
        return {tuple(k) if not isinstance(k, int) else (k, 0): (v if isinstance(v, tuple) else (str(v), None))
                for k, v in spec.items()}
    if isinstance(spec, (str, Path)):
        return read_lyp(spec)
    raise ValueError("layer_map is 'sky130', a dictionary, or a KLayout .lyp file")


def read_lyp(path) -> dict:
    """Layer names and colours from a KLayout layer-properties file (``.lyp``)."""
    import xml.etree.ElementTree as ET
    from .authoring import project_path
    root = ET.parse(project_path(path)).getroot()
    out = {}
    for props in root.iter("properties"):
        source = (props.findtext("source") or "").strip()
        m = re.match(r"(?:[^@]*?)?(\d+)/(\d+)", source.split("@")[0].strip().split(" ")[-1])
        if not m:
            continue
        name = (props.findtext("name") or "").strip() or f"{m.group(1)}/{m.group(2)}"
        name = re.sub(r"\s*\d+/\d+.*$", "", name) or name
        colour = (props.findtext("fill-color") or props.findtext("frame-color") or "").strip() or None
        out[(int(m.group(1)), int(m.group(2)))] = (name, colour)
    return out

# -- Magic ----------------------------------------------------------------------------

_MAGIC_COLOURS = [
    (r"^(dnwell|nwell|pwell|nw|pw)$", "#b9d9a5"), (r"diff|tap|nsd|psd|mvn|mvp", "#3f9b52"),
    (r"^(poly|p)$|polysilicon", "#c0392b"), (r"cont|^licon|^pc$|^ndc|^pdc|^nsc|^psc|^viali|^mcon|^via\d*$|^v\d",
                                            "#3a2a2a"),
    (r"^(locali|li|li1)$", "#9b59b6"), (r"^(metal1|m1)$", "#2e5fb8"), (r"^(metal2|m2)$", "#d0517a"),
    (r"^(metal3|m3)$", "#1aa3a3"), (r"^(metal4|m4)$", "#d8a31a"), (r"^(metal5|m5)$", "#7f8c8d"),
    (r"cap|mim", "#e67e22"), (r"res", "#a04000"),
]
#: Magic's lambda in micrometres, for technologies whose scale is known.
LAMBDA = {"sky130A": 0.01, "sky130B": 0.01}


def read_magic(path, *, depth: int = 4, lambda_um: float | None = None) -> Layout:
    """A Magic layout (``.mag``), with the subcells it uses that sit beside it.

    Lengths are in micrometres for sky130; otherwise in Magic's lambda unless
    ``lambda_um`` gives its size.
    """
    from .authoring import project_path
    path = project_path(path)
    cells: dict[str, Cell] = {}
    names: dict[str, str] = {}
    info = {"tech": "", "scale": 1.0}

    def load(file: Path, level: int) -> Cell | None:
        name = file.stem
        if name in cells:
            return cells[name]
        if not file.exists():
            return None
        cell = Cell(name)
        cells[name] = cell
        section = None
        current = None
        for raw in file.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line:
                continue
            parts = line.split()
            if line.startswith("<<"):
                section = line.strip("<> ").strip()
                current = None
                continue
            if parts[0] == "tech" and file == path:
                info["tech"] = parts[1]
            elif parts[0] == "magscale" and len(parts) == 3 and file == path:
                info["scale"] = int(parts[1]) / int(parts[2])
            elif parts[0] in ("rect", "tri") and section not in (None, "labels", "properties", "end", "checkpaint"):
                x0, y0, x1, y1 = (int(v) for v in parts[1:5])
                cell.polygons.append((section, 0, [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]))
            elif parts[0] in ("rlabel", "flabel") and len(parts) >= 7:
                coords = [int(v) for v in parts[3:7]] if parts[0] == "rlabel" else [int(v) for v in parts[3:7]]
                text = parts[-1]
                cell.texts.append((parts[1], 0, (coords[0] + coords[2]) / 2, (coords[1] + coords[3]) / 2, text))
            elif parts[0] == "use" and len(parts) >= 2:
                current = {"cell": parts[1], "transform": (1, 0, 0, 0, 1, 0), "array": None}
                cell.refs.append((parts[1], current))  # filled in below
            elif parts[0] == "transform" and current is not None:
                a, b, c, d, e, f = (int(v) for v in parts[1:7])
                current["transform"] = (a, b, c, d, e, f)
            elif parts[0] == "array" and current is not None:
                current["array"] = tuple(int(v) for v in parts[1:7])
            elif parts[0] == "box" and current is not None:
                current["box"] = tuple(int(v) for v in parts[1:5])
        resolved = []
        for child, ref in cell.refs:
            names[child] = child
            if level < depth:
                load(file.parent / f"{child}.mag", level + 1)
            t = tuple(float(v) for v in ref["transform"])
            array = ref.get("array")
            if array:
                xlo, xhi, xsep, ylo, yhi, ysep = array
                for i in range(xhi - xlo + 1):
                    for j in range(yhi - ylo + 1):
                        resolved.append((child, (t[0], t[1], t[2] + i * xsep * t[0] + j * ysep * t[1],
                                                 t[3], t[4], t[5] + i * xsep * t[3] + j * ysep * t[4])))
            else:
                resolved.append((child, t))
            if child not in cells and "box" in ref:  # an unread subcell: its bounding box stands in
                bx0, by0, bx1, by1 = ref["box"]
                stand_in = cells.setdefault(child, Cell(child))
                if not stand_in.polygons:
                    stand_in.polygons.append(("subcell", 0, [(bx0, by0), (bx1, by0), (bx1, by1), (bx0, by1)]))
        cell.refs = resolved
        return cell

    load(path, 0)
    lam = lambda_um if lambda_um is not None else LAMBDA.get(info["tech"])
    unit = (lam * 1e-6 * info["scale"]) if lam else 1e-6 * info["scale"]
    layer_names = sorted({l for c in cells.values() for l, *_ in c.polygons})
    mapping = {}
    for k, name in enumerate(layer_names):
        colour = next((col for pattern, col in _MAGIC_COLOURS if re.search(pattern, name)), _PALETTE[k % len(_PALETTE)])
        mapping[(name, 0)] = (name, colour)
    layout = Layout(cells, unit=unit, name=path.stem, path=path, layer_map=mapping, source="Magic")
    if not lam:
        layout._um = lambda value: ureg.Quantity(round(value * info["scale"], 3), "dimensionless")  # in lambda
    return layout

# -- OpenLane -------------------------------------------------------------------------


class Metrics(dict):
    """OpenLane/LibreLane run metrics: ``m["design__instance__count"]`` or ``m.design__instance__count``."""

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key) from None

    def find(self, pattern: str) -> dict:
        """The metrics whose names contain ``pattern``: ``m.find("timing__setup__ws")``."""
        return {k: v for k, v in self.items() if pattern.lower() in k.lower()}

    def table(self, *keys: str, titles: dict | None = None, **options):
        """The named metrics (or a summary of the usual ones) as a table."""
        from .content import Column, Table
        titles = titles or {}
        if not keys:
            keys = tuple(k for k in _SUMMARY if k in self)
        rows = [(titles.get(k, _SUMMARY.get(k, k)), self[k]) for k in keys]
        return Table([Column("metric", "Metric"), Column("value", "Value")], rows, **options)

    def kip_content(self, kind: str):
        return self.table() if kind == "table" else self

    def kip_summary(self) -> str:
        return f"metrics: {len(self)} values"


_SUMMARY = {
    "design__die__area": "Die area (µm²)", "design__core__area": "Core area (µm²)",
    "design__instance__count": "Cells", "design__instance__utilization": "Utilisation",
    "timing__setup__ws": "Worst setup slack (ns)", "timing__hold__ws": "Worst hold slack (ns)",
    "timing__setup__tns": "Total setup slack (ns)", "power__total": "Total power (W)",
    "route__wirelength": "Wire length (µm)", "route__drc_errors": "Routing DRC errors",
    "magic__drc_error__count": "Magic DRC errors", "klayout__drc_error__count": "KLayout DRC errors",
    "design__lvs_error__count": "LVS errors", "antenna__violating__nets": "Antenna violations",
    # OpenLane 1
    "DIEAREA_mm^2": "Die area (mm²)", "CellPer_mm^2": "Cells per mm²", "synth_cell_count": "Cells",
    "wire_length": "Wire length (µm)", "tritonRoute_violations": "Routing DRC errors",
    "Magic_violations": "Magic DRC errors", "lvs_total_errors": "LVS errors", "spef_wns": "Worst slack (ns)",
}


def _value(text):
    if not isinstance(text, str):
        return text
    try:
        return int(text)
    except ValueError:
        try:
            return float(text)
        except ValueError:
            return text


def read_metrics(path) -> Metrics:
    """OpenLane/LibreLane metrics: ``metrics.json`` (2.x) or ``metrics.csv`` (1.x)."""
    import csv
    import json
    from .authoring import project_path
    path = project_path(path)
    text = path.read_text(encoding="utf-8", errors="replace")
    if text.lstrip().startswith("{"):
        data = json.loads(text)
        if "metrics" in data and isinstance(data["metrics"], dict):
            data = data["metrics"]
        return Metrics({k: _value(v) for k, v in data.items()})
    rows = list(csv.DictReader(text.splitlines()))
    if not rows:
        raise ValueError(f"{path.name}: no metrics")
    return Metrics({k: _value(v) for k, v in rows[-1].items() if k})
