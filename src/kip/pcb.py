"""Printed circuit boards: KiCad layouts, Gerber and drill files, and the sums.

- :class:`Board` reads a KiCad layout (``.kicad_pcb``): its outline and size,
  layers, footprints, tracks, vias, zones and holes. A draw cell shows it as
  the fabricated board would look (``view="top"`` or ``"bottom"``) or as its
  copper layers (``view="copper"``); a table cell shows its bill of materials.
- :func:`read_gerbers` reads the fabrication files any PCB tool writes --
  RS-274X Gerbers and Excellon drill files, from a folder or a zip -- and
  draws the board from them the same way, with its size and drill table.
- :func:`trace_width` (IPC-2221), :func:`microstrip` and :func:`stripline`
  are calculations: a calc cell that binds one renders its equations::

    # %% calc supply_trace "Supply trace width"
    supply = trace_width(I=2 * A, dT=10 * K, t=35 * um)
"""
from __future__ import annotations

import math
import re
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

from .sexpr import Node, parse
from .svg import INK, MONO, Canvas
from .units import ureg

__all__ = ["Board", "Gerber", "Drill", "GerberSet", "read_gerbers", "read_gerber", "read_drill",
           "trace_width", "microstrip", "stripline", "read_bom", "read_placement"]

#: How a fabricated board looks: solder mask, copper beneath it, gold pads, white legend.
FINISH = {"mask": "#285f3e", "copper": "#3d7f54", "pad": "#c9a24a", "silk": "#f1efe6",
          "hole": "#1d1f1c", "edge": "#163a25", "paste": "#b7b7b7"}
#: Copper layers in the copper view, top first.
COPPER = ("#c0392b", "#2e5fb8", "#c9a227", "#2c9a63", "#8e44ad", "#d35400", "#16a085", "#7f8c8d")

# -- geometry -------------------------------------------------------------------------


def _rot(x, y, degrees):
    """Turn (x, y) counter-clockwise on a page whose y runs down."""
    if not degrees:
        return x, y
    c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    return x * c + y * s, -x * s + y * c


def _arc3(start, mid, end, step_deg: float = 6.0):
    """Points of the circular arc through three points."""
    from .schematic import _arc_points
    return _arc_points(start, mid, end, steps=max(4, int(180 / step_deg)))


def _d(points, closed=True) -> str:
    if not points:
        return ""
    head = f"M{points[0][0]:.3f} {points[0][1]:.3f}"
    body = "".join(f"L{x:.3f} {y:.3f}" for x, y in points[1:])
    return head + body + ("Z" if closed else "")


def _loops(paths, tol: float = 0.02):
    """Join open polylines end to end into closed loops (a board outline)."""
    paths = [list(p) for p in paths if len(p) >= 2]
    loops = []
    while paths:
        loop = paths.pop(0)
        changed = True
        while changed and math.dist(loop[0], loop[-1]) > tol:
            changed = False
            for i, p in enumerate(paths):
                if math.dist(loop[-1], p[0]) <= tol:
                    loop += p[1:]
                elif math.dist(loop[-1], p[-1]) <= tol:
                    loop += p[-2::-1]
                elif math.dist(loop[0], p[-1]) <= tol:
                    loop = p[:-1] + loop
                elif math.dist(loop[0], p[0]) <= tol:
                    loop = p[:0:-1] + loop
                else:
                    continue
                paths.pop(i)
                changed = True
                break
        if math.dist(loop[0], loop[-1]) <= tol and len(loop) > 3:
            loops.append(loop)
    return loops


def _area(loop) -> float:
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(loop, loop[1:] + loop[:1]))) / 2


def _bbox(points):
    xs, ys = zip(*points)
    return min(xs), min(ys), max(xs), max(ys)


def _mm(value) -> "ureg.Quantity":
    return ureg.Quantity(round(float(value), 4), "mm")

# -- KiCad boards ---------------------------------------------------------------------


def _pts(node: Node):
    """``(pts (xy ..) (arc (start)(mid)(end)) ...)`` as points."""
    out = []
    pts = node.find("pts")
    if pts is None:
        return out
    for child in pts.children():
        if child.name == "xy":
            out.append((float(child[1]), float(child[2])))
        elif child.name == "arc":
            s, m, e = child.xy("start"), child.xy("mid"), child.xy("end")
            out += _arc3(s[:2], m[:2], e[:2])
    return out


def _shape_points(item: Node, pt=lambda x, y: (x, y)):
    """A gr_/fp_ shape as (points, closed)."""
    kind = item.name.split("_", 1)[-1]
    if kind == "line":
        s, e = item.xy("start"), item.xy("end")
        return [pt(*s[:2]), pt(*e[:2])], False
    if kind == "rect":
        (x1, y1, _), (x2, y2, _) = item.xy("start"), item.xy("end")
        return [pt(x1, y1), pt(x2, y1), pt(x2, y2), pt(x1, y2), pt(x1, y1)], True
    if kind == "circle":
        (cx, cy, _), (ex, ey, _) = item.xy("center"), item.xy("end")
        r = math.dist((cx, cy), (ex, ey))
        return [pt(cx + r * math.cos(a * math.pi / 36), cy + r * math.sin(a * math.pi / 36))
                for a in range(73)], True
    if kind == "arc":
        s, m, e = item.xy("start"), item.xy("mid"), item.xy("end")
        return [pt(*p) for p in _arc3(s[:2], m[:2], e[:2])], False
    if kind == "poly":
        points = [pt(*p) for p in _pts(item)]
        return points + points[:1], True
    if kind == "curve":
        p = [pt(*q) for q in _pts(item)]
        if len(p) == 4:
            return [((1 - t) ** 3 * p[0][0] + 3 * (1 - t) ** 2 * t * p[1][0] + 3 * (1 - t) * t * t * p[2][0]
                     + t ** 3 * p[3][0],
                     (1 - t) ** 3 * p[0][1] + 3 * (1 - t) ** 2 * t * p[1][1] + 3 * (1 - t) * t * t * p[2][1]
                     + t ** 3 * p[3][1]) for t in (k / 20 for k in range(21))], False
    return [], False


def _layers_of(node: Node) -> list[str]:
    layers = node.find("layers")
    if layers is not None:
        return [str(v) for v in layers[1:]]
    layer = node.value("layer")
    return [layer] if layer else []


def _width(item: Node) -> float:
    stroke = item.find("stroke")
    if stroke is not None:
        return stroke.number("width", 0.1)
    return item.number("width", 0.1)


def _filled(item: Node) -> bool:
    fill = item.find("fill")
    if fill is None:
        return False
    return len(fill) > 1 and fill[1] in ("solid", "yes") or fill.value("type") == "solid"


class Pad:
    """A footprint pad, in board coordinates."""

    def __init__(self, node: Node, fx: float, fy: float, frot: float, ref: str):
        self.number = node[1] if len(node) > 1 else ""
        self.type = node[2] if len(node) > 2 else "smd"
        self.shape = node[3] if len(node) > 3 else "rect"
        px, py, angle = node.xy()
        dx, dy = _rot(px, py, frot)
        self.x, self.y, self.angle = fx + dx, fy + dy, angle
        size = node.find("size")
        self.w, self.h = (float(size[1]), float(size[2])) if size is not None else (1.0, 1.0)
        drill = node.find("drill")
        self.drill = 0.0
        self.slot = None
        if drill is not None:
            values = [v for v in drill[1:] if isinstance(v, str)]
            if values and values[0] == "oval":
                nums = [float(v) for v in values[1:3]]
                self.drill = min(nums) if nums else 0.0
                self.slot = tuple(nums) if len(nums) == 2 else None
            elif values:
                try:
                    self.drill = float(values[0])
                except ValueError:
                    pass
        self.layers = _layers_of(node)
        net = node.find("net")
        self.net = net[2] if net is not None and len(net) > 2 else (net[1] if net is not None and len(net) > 1
                                                                      and not str(net[1]).isdigit() else "")
        self.ratio = node.number("roundrect_rratio", 0.25)
        self.ref = ref
        self.primitives = node.find("primitives")
        self.frot = frot
        self.fx, self.fy = fx, fy

    @property
    def plated(self) -> bool:
        return self.type == "thru_hole"

    def on(self, layer: str) -> bool:
        side = layer.split(".")[0]
        return layer in self.layers or f"*.{layer.split('.', 1)[-1]}" in self.layers or \
            (side in ("F", "B") and "F&B.Cu" in self.layers and layer.endswith("Cu"))

    def outline(self, grow: float = 0.0):
        """The pad's shape as a closed polygon."""
        w, h = self.w + 2 * grow, self.h + 2 * grow
        if self.shape == "circle":
            r = w / 2
            return [(self.x + r * math.cos(a * math.pi / 18), self.y + r * math.sin(a * math.pi / 18))
                    for a in range(36)]
        if self.shape in ("oval", "roundrect"):
            r = min(w, h) / 2 if self.shape == "oval" else min(w, h) * self.ratio
            local = _rounded(w, h, r)
        else:
            local = [(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)]
        out = []
        for x, y in local:
            rx, ry = _rot(x, y, self.angle)
            out.append((self.x + rx, self.y + ry))
        return out

    def custom(self):
        """A custom pad's extra polygons, in board coordinates."""
        if self.primitives is None:
            return []
        shapes = []
        for prim in self.primitives.children():
            def pt(x, y):
                rx, ry = _rot(x, y, self.angle)
                return self.x + rx, self.y + ry
            points, closed = _shape_points(prim, pt)
            if points:
                shapes.append((points, closed, _width(prim)))
        return shapes


def _rounded(w, h, r):
    r = max(0.0, min(r, w / 2, h / 2))
    pts = []
    for cx, cy, a0 in ((w / 2 - r, -h / 2 + r, -90), (w / 2 - r, h / 2 - r, 0), (-w / 2 + r, h / 2 - r, 90),
                       (-w / 2 + r, -h / 2 + r, 180)):
        for k in range(7):
            a = math.radians(a0 + 15 * k)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


class Footprint:
    """A placed footprint: reference, value, side, position, and its pads."""

    def __init__(self, node: Node):
        self.node = node
        self.name = node[1] if len(node) > 1 and isinstance(node[1], str) else ""
        self.layer = node.value("layer", "F.Cu")
        self.x, self.y, self.rotation = node.xy()
        self.fields = {}
        for prop in node.findall("property"):
            if len(prop) > 2:
                self.fields[prop[1]] = prop[2]
        for text in node.findall("fp_text"):  # KiCad 6
            if len(text) > 2 and text[1] in ("reference", "value"):
                self.fields.setdefault(text[1].title(), text[2])
        attr = node.find("attr")
        words = [str(w) for w in attr[1:]] if attr is not None else []
        self.smd = "smd" in words
        self.through_hole = "through_hole" in words
        self.in_bom = "exclude_from_bom" not in words
        self.dnp = "dnp" in words
        self.virtual = "virtual" in words or "board_only" in words
        self.pads = [Pad(p, self.x, self.y, self.rotation, self.reference) for p in node.findall("pad")]

    @property
    def reference(self) -> str:
        return self.fields.get("Reference", "")

    @property
    def value(self) -> str:
        return self.fields.get("Value", "")

    @property
    def side(self) -> str:
        return "bottom" if self.layer.startswith("B.") else "top"

    def local(self, x, y):
        dx, dy = _rot(x, y, self.rotation)
        return self.x + dx, self.y + dy

    def __repr__(self) -> str:
        return f"<Footprint {self.reference} {self.value} {self.name}>"


class Board:
    """A KiCad PCB layout (``.kicad_pcb``).

    ``board.size`` is the outline's width and height; ``board.copper_layers``,
    ``board.footprints``, ``board.vias``, ``board.min_track``, ``board.min_drill``
    and :meth:`drill_table` describe what a fab will be asked to make.
    In a draw cell it is drawn as made; in a table cell its bill of materials.
    """

    def __init__(self, root: Node, *, path: Path | None = None, source: bytes | None = None):
        if root.name != "kicad_pcb":
            raise ValueError("not a KiCad board (it does not start with (kicad_pcb ...))")
        self.root, self.path, self.source = root, path, source
        general = root.find("general")
        self.thickness = _mm(general.number("thickness", 1.6) if general is not None else 1.6)
        self.layer_names: list[str] = []
        layers = root.find("layers")
        for layer in layers.children() if layers is not None else []:
            if len(layer) > 1:
                self.layer_names.append(str(layer[1]))
        #: net code -> name; KiCad 10 names nets on each item, with no table, and a
        #: name stands for itself
        self.nets = {}
        for net in root.findall("net"):
            if len(net) > 2:
                self.nets[str(net[1])] = net[2]
        self.footprints = [Footprint(f) for f in root.findall("footprint") + root.findall("module")]
        self.segments = root.findall("segment")
        self.arcs = root.findall("arc")
        self.vias = root.findall("via")
        self.zones = root.findall("zone")
        self.graphics = [n for n in root.children() if n.name.startswith("gr_")]

    @classmethod
    def load(cls, path) -> "Board":
        from .authoring import project_path
        path = project_path(path)
        data = path.read_bytes()
        return cls(parse(data.decode("utf-8")), path=path, source=data)

    @property
    def name(self) -> str:
        return self.path.stem if self.path else "board"

    # what it is

    @property
    def copper_layers(self) -> list[str]:
        order = {"F.Cu": -1, "B.Cu": 999}
        cu = [n for n in self.layer_names if n.endswith(".Cu")]
        return sorted(cu, key=lambda n: order.get(n, int(re.sub(r"\D", "", n) or 0)))

    def _outline_paths(self):
        paths = []
        for g in self.graphics:
            if g.value("layer") == "Edge.Cuts":
                points, _ = _shape_points(g)
                if points:
                    paths.append(points)
        for fp in self.footprints:
            for g in fp.node.children():
                if g.name.startswith("fp_") and g.value("layer") == "Edge.Cuts":
                    points, _ = _shape_points(g, fp.local)
                    if points:
                        paths.append(points)
        return paths

    @property
    def outline(self) -> list[list[tuple[float, float]]]:
        """The board edge as closed loops, the outer one first."""
        loops = _loops(self._outline_paths())
        return sorted(loops, key=_area, reverse=True)

    def _extent(self):
        paths = self._outline_paths()
        points = [p for path in paths for p in path]
        if not points:
            points = [(p.x, p.y) for f in self.footprints for p in f.pads] or [(0.0, 0.0)]
        return _bbox(points)

    @property
    def size(self) -> tuple:
        """Width and height of the board outline."""
        x0, y0, x1, y1 = self._extent()
        return _mm(x1 - x0), _mm(y1 - y0)

    @property
    def area(self):
        loops = self.outline
        if loops:
            return ureg.Quantity(round(_area(loops[0]) - sum(_area(l) for l in loops[1:]), 3), "mm**2")
        w, h = self.size
        return w * h

    @property
    def pads(self) -> list[Pad]:
        return [p for f in self.footprints for p in f.pads]

    @property
    def min_track(self):
        widths = [s.number("width", 0) for s in self.segments + self.arcs if s.number("width", 0) > 0]
        return _mm(min(widths)) if widths else None

    @property
    def track_widths(self) -> list:
        return [_mm(w) for w in sorted({s.number("width", 0) for s in self.segments + self.arcs})]

    def track_length(self, net: str | None = None):
        """Total routed length, of one net or of all."""
        keys = None
        if net is not None:
            names = (net, "/" + net.lstrip("/"))
            keys = {k for k, v in self.nets.items() if v in names}
            keys |= {n for n in names if any(str(t.value("net")) == n for t in self.segments + self.arcs)}
            if not keys:
                raise KeyError(f"no net {net!r} on this board")
        total = 0.0
        for s in self.segments:
            if keys is None or str(s.value("net")) in keys:
                total += math.dist(s.xy("start")[:2], s.xy("end")[:2])
        for a in self.arcs:
            if keys is None or str(a.value("net")) in keys:
                pts = _arc3(a.xy("start")[:2], a.xy("mid")[:2], a.xy("end")[:2])
                total += sum(math.dist(p, q) for p, q in zip(pts, pts[1:]))
        return _mm(total)

    @property
    def holes(self) -> list[tuple[float, bool]]:
        """Every drilled hole: (diameter, plated)."""
        out = [(p.drill, p.plated) for p in self.pads if p.drill > 0]
        out += [(v.number("drill", 0.3), True) for v in self.vias]
        return out

    @property
    def min_drill(self):
        holes = [d for d, _ in self.holes if d > 0]
        return _mm(min(holes)) if holes else None

    def drill_table(self, **options):
        """Hole sizes with their counts, plated and not."""
        return _drill_table(self.holes, **options)

    def bom(self, *fields: str, titles: dict | None = None, **options):
        from .schematic import bom_table
        parts = [(f.reference, f.value, f.name, f.dnp, f.fields) for f in self.footprints
                 if f.in_bom and f.reference and not f.reference.startswith("#") and not f.virtual]
        return bom_table(parts, fields, titles, **options)

    def placement(self, **options):
        """Pick-and-place: each footprint's position, rotation and side."""
        from .content import Column, Table
        x0, _, _, y1 = self._extent()
        rows = [(f.reference, f.value, f.name.split(":")[-1], round(f.x - x0, 3), round(y1 - f.y, 3),
                 round(f.rotation, 1), f.side) for f in self.footprints if f.reference]
        return Table([Column("ref", "Ref."), Column("value", "Value"), Column("footprint", "Footprint"),
                      Column("x", "X (mm)"), Column("y", "Y (mm)"), Column("rot", "Rot. (°)"),
                      Column("side", "Side")], rows, **options)

    def summary_table(self, **options):
        """What a fab quote asks for: size, layers, thickness, holes, minimum features."""
        from .content import Column, Table
        w, h = self.size
        rows = [("Size", f"{w.magnitude:g} × {h.magnitude:g} mm"),
                ("Copper layers", str(len(self.copper_layers))),
                ("Thickness", f"{self.thickness.magnitude:g} mm"),
                ("Footprints", str(len([f for f in self.footprints if f.reference]))),
                ("Pads", f"{sum(1 for p in self.pads if p.type == 'smd')} SMD, "
                         f"{sum(1 for p in self.pads if p.type in ('thru_hole', 'np_thru_hole'))} through-hole"),
                ("Vias", str(len(self.vias))),
                ("Holes", str(len(self.holes)))]
        if self.min_track is not None:
            rows.append(("Narrowest track", f"{self.min_track.magnitude:g} mm"))
        if self.min_drill is not None:
            rows.append(("Smallest hole", f"{self.min_drill.magnitude:g} mm"))
        return Table([Column("item", "Item"), Column("value", "Value")], rows, **options)

    # drawing

    def drawing(self, *, view: str = "top", layers=None, width: float = 120, caption: str | None = None,
                attach: bool = True):
        """The board as fabricated (``view="top"`` or ``"bottom"``), or its copper
        (``view="copper"``; ``layers=["F.Cu", "In1.Cu"]`` picks which), ``width`` mm wide."""
        if view not in ("top", "bottom", "copper"):
            raise ValueError("view is 'top', 'bottom' or 'copper'")
        canvas = self._finished(view) if view in ("top", "bottom") else self._copper(layers)
        attachments = {self.path.name: self.source} if attach and self.path and self.source else {}
        return canvas.drawing(width=width, caption=caption, attachments=attachments, margin=1.0,
                              enlarge=True)

    def _board_shape(self, canvas, fill, stroke=None, flip=None):
        loops = self.outline
        if loops:
            d = " ".join(_d([flip(p) for p in loop] if flip else loop) for loop in loops)
            pts = [flip(p) if flip else p for loop in loops for p in loop]
            canvas.path(d, pts, stroke=stroke, width=0.15, fill=fill, evenodd=True)
        else:
            x0, y0, x1, y1 = self._extent()
            canvas.rect(x0, y0, x1 - x0, y1 - y0, fill=fill, stroke=stroke, width=0.15)

    def _layer_items(self, layer: str, flip=None):
        """(kind, points, closed, width) for everything drawn on ``layer``."""
        f = flip or (lambda p: p)
        items = []
        for s in self.segments:
            if s.value("layer") == layer:
                items.append(("track", [f(s.xy("start")[:2]), f(s.xy("end")[:2])], False, s.number("width", 0.2)))
        for a in self.arcs:
            if a.value("layer") == layer:
                pts = _arc3(a.xy("start")[:2], a.xy("mid")[:2], a.xy("end")[:2])
                items.append(("track", [f(p) for p in pts], False, a.number("width", 0.2)))
        for z in self.zones:
            for fp in z.findall("filled_polygon"):
                if fp.value("layer") == layer or (fp.value("layer") is None and layer in _layers_of(z)):
                    items.append(("zone", [f(p) for p in _pts(fp)], True, 0.0))
        for g in self.graphics:
            if g.value("layer") == layer and g.name != "gr_text":
                points, closed = _shape_points(g)
                if points:
                    items.append(("graphic", [f(p) for p in points], closed and _filled(g), _width(g)))
        for fp in self.footprints:
            for g in fp.node.children():
                if g.name.startswith("fp_") and g.name not in ("fp_text",) and g.value("layer") == layer:
                    points, closed = _shape_points(g, fp.local)
                    if points:
                        items.append(("graphic", [f(p) for p in points], closed and _filled(g), _width(g)))
        return items

    def _texts(self, layer: str):
        """(x, y, text, font, angle, justify) of the text on ``layer``."""
        out = []
        for g in self.graphics:
            if g.name == "gr_text" and g.value("layer") == layer and len(g) > 1:
                x, y, angle = g.xy()
                out.append((x, y, g[1], _text_font(g), angle, _justify(g)))
        for fp in self.footprints:
            texts = [t for t in fp.node.findall("property") if len(t) > 2 and t.value("layer") == layer]
            texts += [t for t in fp.node.findall("fp_text") if len(t) > 2 and t.value("layer") == layer]
            for t in texts:
                effects = t.find("effects")
                if t.flag("hide") or (effects is not None and effects.flag("hide")):
                    continue
                text = t[2]
                if text.startswith("${") or not text.strip():
                    text = fp.reference if "REFERENCE" in text.upper() else ""
                if not text:
                    continue
                lx, ly, angle = t.xy()
                x, y = fp.local(lx, ly)
                out.append((x, y, text, _text_font(t), angle, _justify(t)))
        return out

    def _finished(self, view: str) -> Canvas:
        canvas = Canvas()
        side = "F" if view == "top" else "B"
        x0, _, x1, _ = self._extent()
        flip = (lambda p: (x0 + x1 - p[0], p[1])) if view == "bottom" else None
        f = flip or (lambda p: p)
        self._board_shape(canvas, FINISH["mask"], flip=flip)
        cu = f"{side}.Cu"
        for kind, points, closed, width in self._layer_items(cu, flip):
            if kind == "zone":
                canvas.polyline(points, fill=FINISH["copper"], stroke=None, closed=True)
            else:
                canvas.polyline(points, stroke=FINISH["copper"], width=max(width, 0.05),
                                fill=FINISH["copper"] if closed else None, closed=closed)
        for v in self.vias:
            layers = _layers_of(v)
            if cu in layers or ("F.Cu" in layers and "B.Cu" in layers):
                x, y, _ = v.xy()
                px, py = f((x, y))
                canvas.circle(px, py, v.number("size", 0.6) / 2, fill=FINISH["copper"])
        mask = f"{side}.Mask"
        for pad in self.pads:
            if pad.on(mask) and (pad.on(cu) or pad.type == "np_thru_hole"):
                colour = FINISH["pad"] if pad.on(cu) else FINISH["mask"]
                canvas.polyline([f(p) for p in pad.outline()], fill=colour, stroke=None, closed=True)
                for points, closed, width in pad.custom():
                    canvas.polyline([f(p) for p in points], fill=colour if closed else None,
                                    stroke=colour, width=width, closed=closed)
        silk = f"{side}.SilkS"
        for kind, points, closed, width in self._layer_items(silk, flip):
            canvas.polyline(points, stroke=FINISH["silk"], width=max(width, 0.1),
                            fill=FINISH["silk"] if closed else None, closed=closed)
        for x, y, text, size, angle, justify in self._texts(silk):
            px, py = f((x, y))
            # Seen from below, text the layout mirrors reads the right way round.
            _board_text(canvas, px, py, text, size, -angle if view == "bottom" else angle, FINISH["silk"],
                        *justify)
        for pad in self.pads:
            if pad.drill > 0:
                px, py = f((pad.x, pad.y))
                if pad.slot:
                    w, h = pad.slot
                    pts = [_rot(x, y, pad.angle) for x, y in _rounded(w, h, min(w, h) / 2)]
                    canvas.polyline([f((pad.x + x, pad.y + y)) for x, y in pts], fill=FINISH["hole"],
                                    stroke=None, closed=True)
                else:
                    canvas.circle(px, py, pad.drill / 2, fill=FINISH["hole"])
        for v in self.vias:
            x, y, _ = v.xy()
            px, py = f((x, y))
            canvas.circle(px, py, v.number("drill", 0.3) / 2, fill=FINISH["hole"])
        self._board_shape(canvas, None, stroke=FINISH["edge"], flip=flip)
        return canvas

    def _copper(self, layers=None) -> Canvas:
        canvas = Canvas()
        chosen = list(layers) if layers else self.copper_layers
        unknown = [l for l in chosen if l not in self.layer_names]
        if unknown:
            raise ValueError(f"no layer {unknown[0]!r}; this board has {', '.join(self.copper_layers)}")
        self._board_shape(canvas, "#fbf8ef", stroke=INK)
        # bottom layers first, so the top is drawn over them
        for layer in reversed(chosen):
            colour = COPPER[self.copper_layers.index(layer) % len(COPPER)] if layer in self.copper_layers else INK
            for kind, points, closed, width in self._layer_items(layer):
                if kind == "zone":
                    canvas.polyline(points, fill=colour, opacity=0.35, stroke=None, closed=True)
                else:
                    canvas.polyline(points, stroke=colour, width=max(width, 0.05), opacity=0.85,
                                    fill=colour if closed else None, closed=closed)
            for pad in self.pads:
                if pad.on(layer):
                    canvas.polyline(pad.outline(), fill=colour, opacity=0.85, stroke=None, closed=True)
        for v in self.vias:
            x, y, _ = v.xy()
            canvas.circle(x, y, v.number("size", 0.6) / 2, fill="#7a7a7a")
        for pad in self.pads:
            if pad.drill > 0:
                canvas.circle(pad.x, pad.y, pad.drill / 2, fill="#fbf8ef")
        for v in self.vias:
            x, y, _ = v.xy()
            canvas.circle(x, y, v.number("drill", 0.3) / 2, fill="#fbf8ef")
        x0, y0, x1, y1 = canvas.bounds
        lx, ly = x0, y1 + 3.0
        for layer in chosen:
            colour = COPPER[self.copper_layers.index(layer) % len(COPPER)] if layer in self.copper_layers else INK
            canvas.rect(lx, ly - 2.1, 2.4, 2.4, fill=colour, rx=0.3)
            canvas.text(lx + 3.2, ly, layer, size=2.8, fill="#3a342b", font="Libertinus Serif")
            lx += 3.2 + 1.4 * len(layer) + 4
        return canvas

    def kip_content(self, kind: str):
        if kind == "table":
            return self.bom()
        if kind == "draw":
            return self.drawing()
        return self

    def kip_summary(self) -> str:
        w, h = self.size
        return (f"board {self.name}: {w.magnitude:g} × {h.magnitude:g} mm, {len(self.copper_layers)} copper "
                f"layers, {len(self.footprints)} footprints, {len(self.vias)} vias")


def _text_font(node: Node) -> tuple[float, float]:
    """KiCad text's (height, width) in mm."""
    effects = node.find("effects")
    font = effects.find("font") if effects is not None else None
    size = font.find("size") if font is not None else None
    if size is None or len(size) < 2:
        return 1.0, 1.0
    return float(size[1]), float(size[2]) if len(size) > 2 else float(size[1])


def _justify(node: Node) -> tuple[str, str]:
    effects = node.find("effects")
    j = effects.find("justify") if effects is not None else None
    words = [w for w in (j[1:] if j is not None else []) if isinstance(w, str)]
    h = "left" if "left" in words else "right" if "right" in words else "center"
    v = "top" if "top" in words else "bottom" if "bottom" in words else "center"
    return h, v


def _board_text(canvas, x, y, text, font, angle, colour, h="center", v="center"):
    """Legend text at its anchor, justified as KiCad sets it and turned to read left
    to right or upward; narrowed to the width of KiCad's stroke font."""
    height, width = font
    a = angle % 360
    if 90 < a <= 270:  # it would read upside down: turn it, and its justification with it
        a -= 180
        h = {"left": "right", "right": "left"}.get(h, h)
        v = {"top": "bottom", "bottom": "top"}.get(v, v)
    lines = str(text).split("\n")
    dx, dy = _rot(0.0, 1.0, a)  # the text's own downward direction
    pitch = height * 1.6
    em = height / 0.73
    stretch = 0.75 * width / (0.602 * em)  # KiCad's letters are about 0.75 of their width setting
    for k, line in enumerate(lines):
        if v == "top":
            off = height / 2 + k * pitch
        elif v == "bottom":
            off = -((len(lines) - 1 - k) * pitch + height / 2)
        else:
            off = (k - (len(lines) - 1) / 2) * pitch
        canvas.text(x + dx * off, y + dy * off, line, size=em, middle=True, angle=a, fill=colour,
                    font=MONO, anchor={"left": "start", "right": "end"}.get(h, "middle"), stretch=stretch)


def _drill_table(holes, **options):
    from .content import Column, Table
    counts = Counter((round(d, 3), plated) for d, plated in holes if d > 0)
    rows = [(f"{d:g}", "plated" if plated else "non-plated", n)
            for (d, plated), n in sorted(counts.items(), key=lambda kv: (not kv[0][1], kv[0][0]))]
    return Table([Column("d", "Diameter (mm)", align="right"), Column("kind", "Kind"),
                  Column("count", "Holes")], rows, **options)

# -- Gerber ---------------------------------------------------------------------------


class _Macro:
    def __init__(self, body: list[str]):
        self.body = body

    def shapes(self, params: list[float]):
        """(dark, points) polygons of the macro at the origin."""
        variables = {i + 1: v for i, v in enumerate(params)}
        out = []
        for stmt in self.body:
            stmt = stmt.strip()
            if not stmt or stmt.startswith("0"):
                continue
            if stmt.startswith("$") and "=" in stmt:
                name, expr = stmt.split("=", 1)
                variables[int(name[1:])] = _eval(expr, variables)
                continue
            fields = [_eval(f, variables) for f in stmt.split(",")]
            code = int(fields[0])
            if code == 1:  # circle: exposure, diameter, x, y[, rotation]
                exp, d, cx, cy = fields[1:5]
                rot = fields[5] if len(fields) > 5 else 0
                cx, cy = _rot_ccw(cx, cy, rot)
                out.append((exp >= 1, [(cx + d / 2 * math.cos(k * math.pi / 16), cy + d / 2 * math.sin(k * math.pi / 16))
                                       for k in range(32)]))
            elif code in (20, 2):  # vector line: exposure, width, x1, y1, x2, y2, rotation
                exp, w, x1, y1, x2, y2 = fields[1:7]
                rot = fields[7] if len(fields) > 7 else 0
                ang = math.atan2(y2 - y1, x2 - x1)
                nx, ny = -math.sin(ang) * w / 2, math.cos(ang) * w / 2
                pts = [(x1 + nx, y1 + ny), (x2 + nx, y2 + ny), (x2 - nx, y2 - ny), (x1 - nx, y1 - ny)]
                out.append((exp >= 1, [_rot_ccw(x, y, rot) for x, y in pts]))
            elif code == 21:  # centre line: exposure, width, height, cx, cy, rotation
                exp, w, h, cx, cy = fields[1:6]
                rot = fields[6] if len(fields) > 6 else 0
                pts = [(cx - w / 2, cy - h / 2), (cx + w / 2, cy - h / 2), (cx + w / 2, cy + h / 2),
                       (cx - w / 2, cy + h / 2)]
                out.append((exp >= 1, [_rot_ccw(x, y, rot) for x, y in pts]))
            elif code == 4:  # outline: exposure, n, x0, y0, ..., rotation
                exp, n = fields[1], int(fields[2])
                coords = fields[3:3 + 2 * (n + 1)]
                rot = fields[3 + 2 * (n + 1)] if len(fields) > 3 + 2 * (n + 1) else 0
                pts = [_rot_ccw(coords[k], coords[k + 1], rot) for k in range(0, len(coords) - 1, 2)]
                out.append((exp >= 1, pts))
            elif code == 5:  # polygon: exposure, vertices, cx, cy, diameter, rotation
                exp, n, cx, cy, d = fields[1:6]
                rot = fields[6] if len(fields) > 6 else 0
                pts = [(cx + d / 2 * math.cos(2 * math.pi * k / n), cy + d / 2 * math.sin(2 * math.pi * k / n))
                       for k in range(int(n))]
                out.append((exp >= 1, [_rot_ccw(x, y, rot) for x, y in pts]))
            elif code == 7:  # thermal: cx, cy, outer, inner, gap, rotation -- as a ring
                cx, cy, outer = fields[1:4]
                out.append((True, [(cx + outer / 2 * math.cos(k * math.pi / 16), cy + outer / 2 * math.sin(k * math.pi / 16))
                                   for k in range(32)]))
        return out


def _rot_ccw(x, y, degrees):
    if not degrees:
        return x, y
    c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    return x * c - y * s, x * s + y * c


def _eval(expr: str, variables: dict) -> float:
    import ast
    import operator
    text = re.sub(r"\$(\d+)", lambda m: repr(variables.get(int(m.group(1)), 0.0)), expr.strip())
    text = text.replace("x", "*").replace("X", "*")
    ops = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
           ast.USub: operator.neg, ast.UAdd: operator.pos}

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant):
            return float(node.value)
        if isinstance(node, ast.BinOp):
            return ops[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp):
            return ops[type(node.op)](ev(node.operand))
        raise ValueError(f"unsupported aperture macro expression {expr!r}")
    return ev(ast.parse(text, mode="eval"))


_FUNCTIONS = [("profile", "outline"), ("copper", "copper"), ("soldermask", "mask"), ("legend", "silk"),
              ("paste", "paste"), ("plated", "drill"), ("nonplated", "drill"), ("drillmap", "other"),
              ("other", "other"), ("assemblydrawing", "other")]


class Gerber:
    """One RS-274X Gerber layer: its file function and the objects on it.

    ``objects`` are ``(dark, kind, points, width)`` with points in millimetres,
    y up as Gerber has it.
    """

    def __init__(self, text: str, *, name: str = ""):
        self.name = name
        self.attributes: dict[str, list[str]] = {}
        self.objects: list[tuple[bool, str, list, float]] = []
        self._parse(text)

    @classmethod
    def load(cls, path) -> "Gerber":
        from .authoring import project_path
        path = project_path(path)
        return cls(path.read_text(encoding="utf-8", errors="replace"), name=path.name)

    @property
    def function(self) -> list[str]:
        """The X2 file function: ``["Copper", "L1", "Top"]``, ``["Soldermask", "Top"]``..."""
        return self.attributes.get("FileFunction", [])

    def _parse(self, text: str) -> None:
        apertures: dict[str, tuple] = {}
        macros: dict[str, _Macro] = {}
        fmt = (4, 6, 4, 6)
        zeros = "L"
        scale = 1.0
        x = y = 0.0
        aperture = None
        mode = "G01"
        multi = True
        region = False
        contour: list = []
        dark = True
        i, n = 0, len(text)

        def coord(value: str, integer: int, decimals: int) -> float:
            if "." in value:
                return float(value) * scale
            sign = -1 if value.startswith("-") else 1
            digits = value.lstrip("+-")
            if zeros == "T":
                digits = digits.ljust(integer + decimals, "0")
            return sign * int(digits or "0") / 10 ** decimals * scale

        def close_contour():
            nonlocal contour
            if region and len(contour) > 2:
                self.objects.append((dark, "region", contour, 0.0))
            contour = []

        while i < n:
            ch = text[i]
            if ch in " \r\n\t":
                i += 1
                continue
            if ch == "%":
                end = text.find("%", i + 1)
                if end == -1:
                    break
                block = text[i + 1:end]
                i = end + 1
                statements = [s.strip() for s in block.split("*") if s.strip()]
                if not statements:
                    continue
                head = statements[0]
                if head.startswith("FS"):
                    m = re.match(r"FS([LTD]?)([AI]?)X(\d)(\d)Y(\d)(\d)", head)
                    if m:
                        zeros = m.group(1) or "L"
                        fmt = tuple(int(v) for v in m.group(3, 4, 5, 6))
                elif head.startswith("MO"):
                    scale = 25.4 if head[2:4] == "IN" else 1.0
                elif head.startswith("AD"):
                    m = re.match(r"ADD(\d+)([A-Za-z_.$][\w.$]*)(?:,(.*))?", head)
                    if m:
                        params = [float(v) * (scale if k < 2 or m.group(2) != "P" else 1.0)
                                  for k, v in enumerate((m.group(3) or "").split("X")) if v.strip()]
                        if m.group(2) == "P" and params:
                            params[0] *= scale
                        apertures[m.group(1)] = (m.group(2), params)
                elif head.startswith("AM"):
                    macros[head[2:]] = _Macro(statements[1:])
                elif head.startswith("LP"):
                    dark = head[2:3] != "C"
                elif head.startswith("TF"):
                    parts = head[2:].lstrip(".").split(",")
                    self.attributes[parts[0]] = parts[1:]
                continue
            end = text.find("*", i)
            if end == -1:
                break
            word = text[i:end].strip()
            i = end + 1
            if not word:
                continue
            if word.startswith("G04") or word.startswith("G4 "):
                continue
            if word in ("M02", "M00", "M2", "M0"):
                break
            for g in re.findall(r"G0*(\d+)", word):
                g = int(g)
                if g in (1, 2, 3):
                    mode = f"G0{g}"
                elif g == 36:
                    region, contour = True, []
                elif g == 37:
                    close_contour()
                    region = False
                elif g == 74:
                    multi = False
                elif g == 75:
                    multi = True
            m = re.search(r"D0*(\d+)$", word)
            if m and int(m.group(1)) >= 10:
                aperture = m.group(1)
                continue
            coords = dict(re.findall(r"([XYIJ])([+-]?[\d.]+)", word))
            if not m and not coords:
                continue
            op = int(m.group(1)) if m else 1
            nx = coord(coords["X"], fmt[0], fmt[1]) if "X" in coords else x
            ny = coord(coords["Y"], fmt[2], fmt[3]) if "Y" in coords else y
            ci = coord(coords["I"], fmt[0], fmt[1]) if "I" in coords else 0.0
            cj = coord(coords["J"], fmt[2], fmt[3]) if "J" in coords else 0.0
            if op == 1:
                if mode == "G01":
                    path = [(x, y), (nx, ny)]
                else:
                    path = _gerber_arc((x, y), (nx, ny), (ci, cj), mode == "G02", multi)
                if region:
                    if not contour:
                        contour = [path[0]]
                    contour += path[1:]
                else:
                    kind, params = apertures.get(aperture, ("C", [0.1]))
                    width = params[0] if kind == "C" and params else (min(params[:2]) if params else 0.1)
                    self.objects.append((dark, "stroke", path, width))
            elif op == 2:
                if region:
                    close_contour()
            elif op == 3 and aperture in apertures:
                self.objects.extend((dark, kind, pts, 0.0) for kind, pts in
                                    _flash(apertures[aperture], macros, nx, ny))
            x, y = nx, ny
        close_contour()

    def extent(self):
        points = [p for _, _, pts, _ in self.objects for p in pts]
        return _bbox(points) if points else (0.0, 0.0, 0.0, 0.0)

    def svg_items(self, colour: str, clear: str | None, flip):
        """SVG markup and points for every object, dark ones in ``colour``."""
        parts, points = [], []
        for dark, kind, pts, width in self.objects:
            fill = colour if dark else clear
            if fill is None:
                continue
            q = [flip(p) for p in pts]
            points += q
            if kind == "stroke":
                parts.append(f"<path d='{_d(q, closed=False)}' fill='none' stroke='{fill}' "
                             f"stroke-width='{max(width, 0.01):.4f}' stroke-linecap='round' stroke-linejoin='round'/>")
            else:
                parts.append(f"<path d='{_d(q)}' fill='{fill}'/>")
        return "".join(parts), points

    def drawing(self, *, width: float = 120, caption: str | None = None, colour: str = INK):
        """This layer alone, in ink on the page, ``width`` mm wide."""
        canvas = Canvas()
        markup, points = self.svg_items(colour, "#f7f2e3", lambda p: (p[0], -p[1]))
        canvas.raw(markup, points)
        return canvas.drawing(width=width, caption=caption, enlarge=True)

    def kip_content(self, kind: str):
        return self.drawing() if kind == "draw" else self

    def kip_summary(self) -> str:
        return f"Gerber {self.name}: {','.join(self.function) or 'no file function'}, {len(self.objects)} objects"


def _gerber_arc(start, end, offset, clockwise: bool, multi: bool):
    (x0, y0), (x1, y1) = start, end
    if multi:
        centres = [(x0 + offset[0], y0 + offset[1])]
    else:
        centres = [(x0 + sx * abs(offset[0]), y0 + sy * abs(offset[1])) for sx in (1, -1) for sy in (1, -1)]
    best = None
    for cx, cy in centres:
        a0 = math.atan2(y0 - cy, x0 - cx)
        a1 = math.atan2(y1 - cy, x1 - cx)
        sweep = (a0 - a1) % (2 * math.pi) if clockwise else (a1 - a0) % (2 * math.pi)
        if multi and sweep == 0 and math.dist(start, end) < 1e-9:
            sweep = 2 * math.pi
        if not multi and sweep > math.pi / 2 + 1e-6:
            continue
        error = abs(math.dist((cx, cy), start) - math.dist((cx, cy), end))
        if best is None or error < best[0]:
            best = (error, cx, cy, a0, sweep)
    if best is None:
        return [start, end]
    _, cx, cy, a0, sweep = best
    r = math.dist((cx, cy), start)
    steps = max(2, int(abs(sweep) / (math.pi / 36)) + 1)
    sign = -1 if clockwise else 1
    return [(cx + r * math.cos(a0 + sign * sweep * k / (steps - 1)), cy + r * math.sin(a0 + sign * sweep * k / (steps - 1)))
            for k in range(steps)]


def _flash(aperture, macros, x, y):
    kind, params = aperture
    out = []
    if kind == "C":
        r = params[0] / 2 if params else 0.05
        out.append(("flash", [(x + r * math.cos(k * math.pi / 16), y + r * math.sin(k * math.pi / 16)) for k in range(32)]))
    elif kind in ("R", "O"):
        w, h = (params + [params[0] if params else 0.1])[:2] if params else (0.1, 0.1)
        local = (_rounded(w, h, min(w, h) / 2) if kind == "O"
                 else [(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)])
        out.append(("flash", [(x + px, y + py) for px, py in local]))
    elif kind == "P" and len(params) >= 2:
        d, n = params[0], int(params[1])
        rot = math.radians(params[2]) if len(params) > 2 else 0.0
        out.append(("flash", [(x + d / 2 * math.cos(rot + 2 * math.pi * k / n), y + d / 2 * math.sin(rot + 2 * math.pi * k / n))
                              for k in range(n)]))
    elif kind in macros:
        for dark, pts in macros[kind].shapes(params):
            if dark:
                out.append(("flash", [(x + px, y + py) for px, py in pts]))
    return out


def read_gerber(path) -> Gerber:
    return Gerber.load(path)

# -- Excellon --------------------------------------------------------------------------


class Drill:
    """An Excellon drill file: every hole, its tool, and whether it is plated."""

    def __init__(self, text: str, *, name: str = ""):
        self.name = name
        self.holes: list[tuple[float, float, float, bool]] = []  # x, y, diameter, plated
        self.slots: list[tuple[float, float, float, float, float, bool]] = []
        self.tools: dict[str, float] = {}
        self._parse(text)

    @classmethod
    def load(cls, path) -> "Drill":
        from .authoring import project_path
        path = project_path(path)
        return cls(path.read_text(encoding="utf-8", errors="replace"), name=path.name)

    def _parse(self, text: str) -> None:
        scale = 1.0
        metric = True
        zeros = "LZ"
        decimals = 3
        plated_file = None
        tool_plated: dict[str, bool] = {}
        pending_plated = None
        tool = None
        x = y = 0.0
        down = None
        upper = self.name.upper()
        if "NPTH" in upper or "NON-PLATED" in upper or "NONPLATED" in upper:
            plated_file = False
        elif "PTH" in upper:
            plated_file = True
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            if line.startswith(";"):
                if "TF.FileFunction" in line:
                    if "NonPlated" in line:
                        plated_file = False
                    elif "Plated" in line and "MixedPlating" not in line:
                        plated_file = True
                if "TA.AperFunction" in line:
                    pending_plated = "NonPlated" not in line
                continue
            if line.startswith(("METRIC", "INCH")):
                metric = line.startswith("METRIC")
                scale = 1.0 if metric else 25.4
                decimals = 3 if metric else 4
                if "TZ" in line:
                    zeros = "TZ"
                m = re.search(r"0+\.(0+)", line)
                if m:
                    decimals = len(m.group(1))
                continue
            m = re.match(r"T0*(\d+)(?:F\d+)?(?:S\d+)?C([\d.]+)", line)
            if m:
                self.tools[m.group(1)] = float(m.group(2)) * scale
                tool_plated[m.group(1)] = pending_plated if pending_plated is not None else (plated_file is not False)
                pending_plated = None
                continue
            m = re.fullmatch(r"T0*(\d+)", line)
            if m:
                tool = m.group(1)
                continue
            if line in ("M15",):
                down = (x, y)
                continue
            if line in ("M16", "M17"):
                down = None
                continue
            coords = re.findall(r"([XY])([+-]?[\d.]+)", line.split("G85")[0])
            if not coords:
                continue

            def value(v):
                if "." in v:
                    return float(v) * scale
                sign = -1 if v.startswith("-") else 1
                digits = v.lstrip("+-")
                if zeros == "TZ":
                    return sign * int(digits) / 10 ** decimals * scale
                return sign * int(digits) / 10 ** decimals * scale
            nx, ny = x, y
            for axis, v in coords:
                if axis == "X":
                    nx = value(v)
                else:
                    ny = value(v)
            d = self.tools.get(tool, 0.0)
            plated = tool_plated.get(tool, plated_file is not False)
            if "G85" in line:
                end = dict(re.findall(r"([XY])([+-]?[\d.]+)", line.split("G85")[1]))
                ex = value(end["X"]) if "X" in end else nx
                ey = value(end["Y"]) if "Y" in end else ny
                self.slots.append((nx, ny, ex, ey, d, plated))
            elif line.startswith("G01") and down is not None:
                self.slots.append((down[0], down[1], nx, ny, d, plated))
            elif not line.startswith("G00"):
                self.holes.append((nx, ny, d, plated))
            x, y = nx, ny

    def __len__(self) -> int:
        return len(self.holes) + len(self.slots)

    @property
    def min_diameter(self):
        sizes = [h[2] for h in self.holes] + [s[4] for s in self.slots]
        return _mm(min(sizes)) if sizes else None

    def table(self, **options):
        return _drill_table([(h[2], h[3]) for h in self.holes] + [(s[4], s[5]) for s in self.slots], **options)

    def kip_content(self, kind: str):
        return self.table() if kind == "table" else self

    def kip_summary(self) -> str:
        return f"drill file {self.name}: {len(self.holes)} holes, {len(self.slots)} slots, {len(self.tools)} tools"


def read_drill(path) -> Drill:
    return Drill.load(path)

# -- a set of fabrication files ----------------------------------------------------------

_EXTENSIONS = {".gtl": ("copper", "top"), ".gbl": ("copper", "bottom"), ".gts": ("mask", "top"),
               ".gbs": ("mask", "bottom"), ".gto": ("silk", "top"), ".gbo": ("silk", "bottom"),
               ".gtp": ("paste", "top"), ".gbp": ("paste", "bottom"), ".gko": ("outline", ""),
               ".gm1": ("outline", ""), ".gml": ("outline", ""), ".gm": ("outline", "")}
_KICAD_NAMES = [("f_cu", "copper", "top"), ("b_cu", "copper", "bottom"), ("f_mask", "mask", "top"),
                ("b_mask", "mask", "bottom"), ("f_silks", "silk", "top"), ("b_silks", "silk", "bottom"),
                ("f_paste", "paste", "top"), ("b_paste", "paste", "bottom"), ("edge_cuts", "outline", "")]


def _role(gerber: Gerber) -> tuple[str, str]:
    """(role, side): what a Gerber is for, from its X2 attributes or else its name."""
    function = [f.lower() for f in gerber.function]
    if function:
        role = next((r for key, r in _FUNCTIONS if function[0] == key), "other")
        side = "top" if "top" in function else "bottom" if "bot" in function else ""
        if role == "copper" and len(function) > 1 and function[1].startswith("l") and side == "":
            side = "inner"
        return role, side
    name = gerber.name.lower()
    suffix = Path(name).suffix
    if suffix in _EXTENSIONS:
        return _EXTENSIONS[suffix]
    for key, role, side in _KICAD_NAMES:
        if key in name.replace("-", "_"):
            return role, side
    if re.search(r"\.g\d+$|in\d+_cu", name):
        return "copper", "inner"
    if "outline" in name or "edge" in name or "profile" in name:
        return "outline", ""
    return "other", ""


class GerberSet:
    """A board's fabrication files: Gerber layers and drill files.

    ``fab.size``, ``fab.copper_layers`` and :meth:`drill_table` are what a
    fab quotes from; in a draw cell the board is drawn from the files as made.
    """

    def __init__(self, gerbers: list[Gerber], drills: list[Drill], *, name: str = ""):
        self.gerbers, self.drills, self.name = gerbers, drills, name
        self.roles = [(g, *_role(g)) for g in gerbers]

    def layer(self, role: str, side: str = "") -> Gerber | None:
        return next((g for g, r, s in self.roles if r == role and (not side or s == side)), None)

    @property
    def copper_layers(self) -> int:
        return sum(1 for _, r, _ in self.roles if r == "copper")

    def _extent(self):
        outline = self.layer("outline")
        source = [outline] if outline else [g for g, r, _ in self.roles if r == "copper"]
        points = [p for g in source for _, _, pts, _ in g.objects for p in pts]
        return _bbox(points) if points else (0.0, 0.0, 0.0, 0.0)

    @property
    def size(self) -> tuple:
        x0, y0, x1, y1 = self._extent()  # the outline's centre line, as the layout measures it
        return _mm(x1 - x0), _mm(y1 - y0)

    @property
    def holes(self) -> list[tuple[float, bool]]:
        return [(h[2], h[3]) for d in self.drills for h in d.holes] + \
               [(s[4], s[5]) for d in self.drills for s in d.slots]

    @property
    def min_drill(self):
        sizes = [d for d, _ in self.holes if d > 0]
        return _mm(min(sizes)) if sizes else None

    def drill_table(self, **options):
        return _drill_table(self.holes, **options)

    def layer_table(self, **options):
        """Each file and what it is for."""
        from .content import Column, Table
        rows = [(g.name, (r + (f" ({s})" if s else "")), len(g.objects)) for g, r, s in self.roles]
        rows += [(d.name, "drill", len(d)) for d in self.drills]
        return Table([Column("file", "File"), Column("role", "Layer"), Column("objects", "Objects")], rows,
                     **options)

    def drawing(self, *, view: str = "top", width: float = 120, caption: str | None = None):
        """The board as made, seen from the top or the bottom, ``width`` mm wide."""
        if view not in ("top", "bottom"):
            raise ValueError("view is 'top' or 'bottom'")
        canvas = Canvas()
        x0, _, x1, _ = self._extent()
        flip = (lambda p: (x0 + x1 - p[0], -p[1])) if view == "bottom" else (lambda p: (p[0], -p[1]))
        outline = self.layer("outline")
        loops = _loops([pts for _, kind, pts, _ in outline.objects if kind == "stroke"]) if outline else []
        if loops:
            loops.sort(key=_area, reverse=True)
            d = " ".join(_d([flip(p) for p in loop]) for loop in loops)
            canvas.path(d, [flip(p) for p in loops[0]], stroke=None, fill=FINISH["mask"], evenodd=True)
        else:
            ex0, ey0, ex1, ey1 = self._extent()
            (ax, ay), (bx, by) = flip((ex0, ey0)), flip((ex1, ey1))
            canvas.rect(min(ax, bx), min(ay, by), abs(bx - ax), abs(by - ay), fill=FINISH["mask"])
        copper, mask, silk = self.layer("copper", view), self.layer("mask", view), self.layer("silk", view)
        if copper is not None:
            markup, points = copper.svg_items(FINISH["copper"], FINISH["mask"], flip)
            canvas.raw(markup, points)
            if mask is not None:
                key = f"kip-mask-{view}"
                openings, _ = mask.svg_items("white", "black", flip)
                bx0, by0, bx1, by1 = canvas.bounds
                region = (f"x='{bx0 - 5:.3f}' y='{by0 - 5:.3f}' width='{bx1 - bx0 + 10:.3f}' "
                          f"height='{by1 - by0 + 10:.3f}'")
                canvas.defs.append(f"<mask id='{key}' maskUnits='userSpaceOnUse' {region}>{openings}</mask>")
                gold, _ = copper.svg_items(FINISH["pad"], FINISH["mask"], flip)
                canvas.raw(f"<g mask='url(#{key})'>{gold}</g>", [])
        if silk is not None:
            markup, points = silk.svg_items(FINISH["silk"], None, flip)
            canvas.raw(markup, points)
        for drill in self.drills:
            for hx, hy, d, _ in drill.holes:
                px, py = flip((hx, hy))
                canvas.circle(px, py, d / 2, fill=FINISH["hole"])
            for sx, sy, ex, ey, d, _ in drill.slots:
                (ax, ay), (bx, by) = flip((sx, sy)), flip((ex, ey))
                canvas.line(ax, ay, bx, by, stroke=FINISH["hole"], width=d)
        if loops:
            d = " ".join(_d([flip(p) for p in loop]) for loop in loops)
            canvas.path(d, [], stroke=FINISH["edge"], width=0.15, fill=None)
        return canvas.drawing(width=width, caption=caption, enlarge=True)

    def kip_content(self, kind: str):
        if kind == "draw":
            return self.drawing()
        if kind == "table":
            return self.drill_table()
        return self

    def kip_summary(self) -> str:
        w, h = self.size
        return (f"fabrication files {self.name}: {w.magnitude:g} × {h.magnitude:g} mm, "
                f"{self.copper_layers} copper layers, {len(self.holes)} holes")


def read_gerbers(path) -> GerberSet:
    """Every Gerber and drill file in a folder or a zip (or a list of files)."""
    from .authoring import project_path
    sources: list[tuple[str, bytes]] = []
    if isinstance(path, (list, tuple)):
        for p in path:
            resolved = project_path(p)
            sources.append((resolved.name, resolved.read_bytes()))
        name = "fabrication"
    else:
        resolved = project_path(path)
        name = resolved.stem
        if resolved.is_dir():
            sources = [(p.name, p.read_bytes()) for p in sorted(resolved.iterdir()) if p.is_file()]
        elif zipfile.is_zipfile(resolved):
            with zipfile.ZipFile(resolved) as z:
                sources = [(Path(i.filename).name, z.read(i)) for i in z.infolist() if not i.is_dir()]
        else:
            sources = [(resolved.name, resolved.read_bytes())]
    gerbers, drills = [], []
    for filename, data in sources:
        text = data.decode("utf-8", errors="replace")
        head = text[:4000]
        if "M48" in head[:200] or re.search(r"^M48\s*$", head, re.M):
            drills.append(Drill(text, name=filename))
        elif "%FS" in head or "%MO" in head or "G04" in head:
            gerbers.append(Gerber(text, name=filename))
    if not gerbers and not drills:
        raise ValueError(f"no Gerber or drill files in {path}")
    return GerberSet(gerbers, drills, name=name)

# -- bills of materials ----------------------------------------------------------------


def _read_rows(path):
    import csv
    from .authoring import project_path
    resolved = project_path(path)
    text = resolved.read_text(encoding="utf-8-sig", errors="replace")
    dialect = csv.Sniffer().sniff(text[:2000], delimiters=",;\t") if text.strip() else csv.excel
    return list(csv.DictReader(text.splitlines(), dialect=dialect))


def read_bom(path, **options):
    """A bill of materials as a CSV file writes it -- KiCad, Altium, JLCPCB -- as a table."""
    from .content import Table
    rows = _read_rows(path)
    if not rows:
        raise ValueError(f"{path}: no rows")
    return Table.from_records(rows, **options)


def read_placement(path, **options):
    """A pick-and-place (centroid) file as a table: KiCad ``.pos`` CSV or any CSV."""
    from .content import Table
    rows = _read_rows(path)
    if not rows:
        raise ValueError(f"{path}: no rows")
    return Table.from_records(rows, **options)

# -- the sums --------------------------------------------------------------------------

from .authoring import calculation  # noqa: E402  (the calculations below render their equations)
from .units import UNIT_NAMES as _U  # noqa: E402

mil = _U["mil"]
mm = _U["mm"]
um = _U["um"]
K = _U["K"]
A = _U["A"]
ohm = _U["ohm"]


#: IPC-2221's constants for outer and inner layers: I = k·ΔT^0.44·A^0.725, A in mil².
IPC2221_EXTERNAL = 0.048 * A / (K ** 0.44 * mil ** 1.45)
IPC2221_INTERNAL = 0.024 * A / (K ** 0.44 * mil ** 1.45)


@calculation
def trace_width(I, dT=10 * K, t=35 * um, external=True):
    """IPC-2221: the narrowest track that carries ``I`` with a temperature rise ``dT``
    in copper ``t`` thick (35 µm is 1 oz); ``external`` for an outer layer."""
    k = IPC2221_EXTERNAL if external else IPC2221_INTERNAL
    # equations
    A_c = (I / (k * dT ** 0.44)) ** (1 / 0.725)   # -> mil**2
    w = A_c / t                                   # -> mm
    return locals()


@calculation
def microstrip(w, h, t=35 * um, e_r=4.3):
    """A surface trace over a plane: Hammerstad and Jensen's characteristic
    impedance, with the strip's thickness folded into an effective width."""
    # equations
    w_e = w + t / pi * log(1 + 4 * e * h / (t * (1 / tanh(sqrt(6.517 * w / h))) ** 2))   # -> mm
    u = w_e / h
    f = 6 + (2 * pi - 6) * exp(-(30.666 / u) ** 0.7528)
    a = 1 + log((u ** 4 + (u / 52) ** 2) / (u ** 4 + 0.432)) / 49 + log(1 + (u / 18.1) ** 3) / 18.7
    b = 0.564 * ((e_r - 0.9) / (e_r + 3)) ** 0.053
    e_eff = (e_r + 1) / 2 + (e_r - 1) / 2 * (1 + 10 / u) ** (-a * b)
    Z_0 = 60 * ohm / sqrt(e_eff) * log(f / u + sqrt(1 + (2 / u) ** 2))   # -> ohm
    return locals()


@calculation
def stripline(w, b, t=35 * um, e_r=4.3):
    """A trace centred between two planes ``b`` apart: IPC-2141's impedance."""
    # equations
    Z_0 = 60 * ohm / sqrt(e_r) * log(4 * b / (0.67 * pi * (0.8 * w + t)))   # -> ohm
    return locals()


from .units import MATH_NAMES as _M  # noqa: E402
pi, e, log, exp, sqrt, tanh = (_M[n] for n in ("pi", "e", "log", "exp", "sqrt", "tanh"))
