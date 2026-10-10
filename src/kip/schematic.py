"""Schematics: KiCad and xschem drawings, and the bill of materials in them.

- :class:`Schematic` reads a KiCad schematic (``.kicad_sch``, KiCad 6 and
  later): its symbols, values and footprints, sheets, and title block. A draw
  cell shows it as a vector drawing, cropped to what is drawn, without KiCad
  installed -- a KiCad schematic carries its own symbol graphics.
- :meth:`Schematic.bom` groups its parts into a bill of materials.
- :class:`XSchematic` reads an xschem schematic (``.sch``); its symbols come
  from the xschem library path (``XSCHEM_LIBRARY_PATH``, ``PDK_ROOT``).
- A `schemdraw <https://schemdraw.readthedocs.io>`_ drawing as the last line
  of a draw cell is shown as it is (``kip[electronics]`` installs schemdraw).
"""
from __future__ import annotations

import math
import os
import re
from collections import defaultdict
from pathlib import Path

from .sexpr import Node, parse
from .svg import INK, MONO, Canvas, escape, text_width

__all__ = ["Schematic", "SchematicSymbol", "XSchematic", "KicadNetlist", "read_schematic",
           "reference_ranges", "bom_table", "from_skidl", "from_schemdraw"]

#: Colours: wires green, symbols dark red on a pale body, fields teal -- KiCad's
#: scheme, darkened for paper.
COLOURS = {
    "wire": "#2b7a3b", "bus": "#2a4f9e", "body": "#8a1c1c", "fill": "#fbf3d0", "pin": "#8a1c1c",
    "field": "#0d5c63", "pin_name": "#0d5c63", "pin_number": "#8a1c1c", "label": INK,
    "global": "#8a1c1c", "junction": "#2b7a3b", "noconnect": "#2a4f9e", "sheet": "#6b3fa0",
    "sheet_fill": "#f6f0fb", "note": "#2a4f9e", "graphic": "#2a4f9e",
}
#: Everything in ink, bodies unfilled: for a document printed in black.
MONOCHROME = {k: ("none" if k in ("fill", "sheet_fill") else INK) for k in COLOURS}

#: An SVG font size per millimetre of KiCad text height (KiCad sizes the capitals).
_EM = 1.36
_LINE = 0.1524  # KiCad's default line width, 6 mil

# -- shared --------------------------------------------------------------------------


def reference_ranges(refs) -> str:
    """``R1, R2, R3, R5`` as ``R1–R3, R5``."""
    def key(ref):
        m = re.match(r"([A-Za-z#_]*)(\d+)(.*)", ref)
        return (m.group(1), int(m.group(2)), m.group(3)) if m else (ref, 0, "")

    items = sorted(set(refs), key=key)
    out, run = [], []

    def flush():
        if len(run) >= 3:
            out.append(f"{run[0]}–{run[-1]}")
        else:
            out.extend(run)

    for ref in items:
        p, n, s = key(ref)
        if run and not s:
            lp, ln, ls = key(run[-1])
            if lp == p and ln == n - 1 and not ls:
                run.append(ref)
                continue
        flush()
        run = [ref]
    flush()
    return ", ".join(out)


def _markup(text: str) -> str:
    """KiCad's ``_{sub}``, ``^{super}`` and ``~{overbar}`` as SVG tspans."""
    out, i = [], 0
    while i < len(text):
        m = re.compile(r"([_^~])\{([^}]*)\}").search(text, i)
        if not m:
            out.append(escape(text[i:]))
            break
        out.append(escape(text[i:m.start()]))
        kind, inner = m.group(1), escape(m.group(2))
        if kind == "_":
            out.append(f"<tspan baseline-shift='sub' font-size='70%'>{inner}</tspan>")
        elif kind == "^":
            out.append(f"<tspan baseline-shift='super' font-size='70%'>{inner}</tspan>")
        else:
            out.append(f"<tspan text-decoration='overline'>{inner}</tspan>")
        i = m.end()
    return "".join(out)


def _plain(text: str) -> str:
    return re.sub(r"[_^~]\{([^}]*)\}", r"\1", text)


def _text(canvas: Canvas, x, y, text, size, *, anchor="middle", valign="middle", angle=0.0,
          colour=INK, bold=False, italic=False):
    """KiCad text of height ``size`` (mm) anchored by its justification."""
    text = str(text)
    if not text:
        return
    fs = size * _EM
    lines = text.split("\n")
    pitch = size * 1.6
    # the baseline of the first line, from the vertical justification
    block = (len(lines) - 1) * pitch
    if valign == "top":
        first = size
    elif valign == "bottom":
        first = -block
    else:
        first = size / 2 - block / 2
    c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    for k, line in enumerate(lines):
        if not line:
            continue
        dy = first + k * pitch
        bx, by = x + dy * s, y + dy * c  # move along the text's own downward direction
        markup = _markup(line)
        style = (" font-weight='bold'" if bold else "") + (" font-style='italic'" if italic else "")
        turn = f" transform='rotate({-angle:.3f} {bx:.3f} {by:.3f})'" if angle else ""
        w = text_width(_plain(line), fs)
        canvas.raw(f"<text x='{bx:.3f}' y='{by:.3f}' font-family='{MONO}' font-size='{fs:.3f}' "
                   f"fill='{colour}' text-anchor='{anchor}'{style}{turn}>{markup}</text>",
                   _text_corners(bx, by, w, size, anchor, angle))


def _text_corners(x, y, w, h, anchor, angle):
    x0 = {"start": 0.0, "middle": -w / 2, "end": -w}[anchor]
    c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    return [(x + px * c + py * s, y - px * s + py * c)
            for px, py in ((x0, 0.25 * h), (x0 + w, 0.25 * h), (x0, -1.05 * h), (x0 + w, -1.05 * h))]


def _justify(effects: Node | None) -> tuple[str, str, bool]:
    """(horizontal, vertical, hidden) from an ``(effects ...)`` node."""
    if effects is None:
        return "center", "center", False
    j = effects.find("justify")
    words = [w for w in (j[1:] if j is not None else []) if isinstance(w, str)]
    h = "left" if "left" in words else "right" if "right" in words else "center"
    v = "top" if "top" in words else "bottom" if "bottom" in words else "center"
    return h, v, effects.flag("hide")


def _font(effects: Node | None) -> tuple[float, bool, bool]:
    if effects is None:
        return 1.27, False, False
    font = effects.find("font")
    if font is None:
        return 1.27, False, False
    size = font.find("size")
    height = float(size[1]) if size is not None and len(size) > 1 else 1.27
    return height, font.flag("bold"), font.flag("italic")


_ANCHOR = {"left": "start", "center": "middle", "right": "end"}
_VALIGN = {"top": "top", "center": "middle", "bottom": "bottom"}

# -- KiCad symbols ------------------------------------------------------------------------


def _matrix(angle: float, mirror: str | None):
    """KiCad's symbol transform: library (y up) to sheet (y down) coordinates."""
    m = [[1, 0], [0, -1]]
    for _ in range(int(round(angle / 90)) % 4):
        m = [[m[1][0], m[1][1]], [-m[0][0], -m[0][1]]]  # turn 90° counter-clockwise on the page
    if mirror == "x":
        m = [[m[0][0], m[0][1]], [-m[1][0], -m[1][1]]]
    elif mirror == "y":
        m = [[-m[0][0], -m[0][1]], [m[1][0], m[1][1]]]
    return m


def _circle_through(p1, p2, p3):
    ax, ay = p1
    bx, by = p2
    cx, cy = p3
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-12:
        return None
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay) + (cx * cx + cy * cy) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx) + (cx * cx + cy * cy) * (bx - ax)) / d
    return ux, uy, math.dist((ux, uy), p1)


def _arc_points(start, mid, end, steps: int = 24):
    """Points along the circular arc from ``start`` through ``mid`` to ``end``."""
    circle = _circle_through(start, mid, end)
    if circle is None:
        return [start, end]
    cx, cy, r = circle
    a0 = math.atan2(start[1] - cy, start[0] - cx)
    am = math.atan2(mid[1] - cy, mid[0] - cx)
    a1 = math.atan2(end[1] - cy, end[0] - cx)

    def ccw(a, b):
        return (b - a) % (2 * math.pi)

    sweep = ccw(a0, a1)
    if ccw(a0, am) > sweep:  # the mid point is on the other side: go clockwise
        sweep -= 2 * math.pi
    n = max(2, int(abs(sweep) / (math.pi / steps)) + 1)
    return [(cx + r * math.cos(a0 + sweep * k / (n - 1)), cy + r * math.sin(a0 + sweep * k / (n - 1)))
            for k in range(n)]


def _stroke(node: Node, default: float = _LINE) -> tuple[float, str | None]:
    stroke = node.find("stroke")
    if stroke is None:
        return default, None
    width = stroke.number("width", 0.0)
    kind = stroke.value("type", "default")
    dash = {"dash": (1.0, 0.6), "dot": (0.1, 0.5), "dash_dot": (1.0, 0.5, 0.1, 0.5)}.get(kind)
    return (width if width > 0 else default), dash


def _fill(node: Node, colours, body: str) -> str | None:
    fill = node.find("fill")
    if fill is None:
        return None
    kind = fill.value("type", "none")
    if kind == "outline":
        return body
    if kind == "background":
        return None if colours["fill"] == "none" else colours["fill"]
    if kind == "color":
        c = fill.find("color")
        if c is not None and len(c) >= 4:
            r, g, b = (int(float(v)) for v in c[1:4])
            alpha = float(c[4]) if len(c) > 4 else 1.0
            if alpha == 0:
                return None
            return f"#{r:02x}{g:02x}{b:02x}"
    return None


class SchematicSymbol:
    """A placed symbol: its reference, value, footprint and every other field."""

    def __init__(self, node: Node, lib: Node | None, unit_count: int):
        self.node, self.lib = node, lib
        self.lib_id = node.value("lib_id", "")
        x, y, angle = node.xy()
        self.at = (x, y)
        self.angle = angle
        self.mirror = node.value("mirror")
        self.unit = int(node.number("unit", 1))
        self.unit_count = unit_count
        self.fields: dict[str, str] = {}
        for prop in node.findall("property"):
            if len(prop) > 2:
                self.fields[prop[1]] = prop[2]
        #: (sheet path, reference, unit) for each placement of this symbol's sheet
        self.instances: list[tuple[str, str, int]] = []
        instances = node.find("instances")
        if instances is not None:
            for project in instances.findall("project"):
                for path in project.findall("path"):
                    if path.value("reference"):
                        self.instances.append((path[1] if len(path) > 1 else "", path.value("reference"),
                                               int(path.number("unit", self.unit))))
        if self.instances:
            self.fields["Reference"] = self.instances[0][1]
            self.unit = self.instances[0][2]
        self.in_bom = node.value("in_bom", "yes") == "yes"
        self.on_board = node.value("on_board", "yes") == "yes"
        self.dnp = node.value("dnp", "no") == "yes"
        self.power = lib is not None and lib.find("power") is not None

    @property
    def reference(self) -> str:
        return self.fields.get("Reference", "?")

    @property
    def value(self) -> str:
        return self.expand(self.fields.get("Value", ""))

    @property
    def footprint(self) -> str:
        return self.fields.get("Footprint", "")

    def expand(self, text: str) -> str:
        """``${REFERENCE}``, ``${VALUE}``, ``${SIM.PARAMS}``... from this symbol's fields."""
        upper = {k.upper(): v for k, v in self.fields.items()}

        def sub(m):
            key = m.group(1).upper()
            if key == "REFERENCE":
                return self.display_reference
            return upper.get(key, m.group(0)) if key != "VALUE" else upper.get("VALUE", "")
        return re.sub(r"\$\{([^}]+)\}", sub, text)

    @property
    def display_reference(self) -> str:
        ref = self.reference
        if self.unit_count > 1 and not ref.endswith("?"):
            return ref + chr(ord("A") + self.unit - 1)
        return ref

    def __getitem__(self, key: str) -> str:
        return self.fields[key]

    def __repr__(self) -> str:
        return f"<SchematicSymbol {self.reference} {self.value}>"


class Schematic:
    """A KiCad schematic sheet: symbols, wires, labels, sheets and its title block.

    ``Schematic.load("input/filter.kicad_sch")``. In a draw cell it is drawn
    cropped to its content; in a table cell its bill of materials. ``.symbols``
    are the placed parts; ``.sheets`` the hierarchical sheets, which
    :meth:`hierarchy` loads too.
    """

    def __init__(self, root: Node, *, path: Path | None = None, source: bytes | None = None):
        if root.name != "kicad_sch":
            raise ValueError("not a KiCad schematic (it does not start with (kicad_sch ...))")
        self.root, self.path, self.source = root, path, source
        self.version = root.value("version", "")
        self.libs: dict[str, Node] = {}
        libs = root.find("lib_symbols")
        if libs is not None:
            for sym in libs.findall("symbol"):
                self.libs[sym[1]] = sym
        self.symbols: list[SchematicSymbol] = []
        for node in root.findall("symbol"):
            lib = self._lib(node)
            self.symbols.append(SchematicSymbol(node, lib, self._unit_count(lib)))
        tb = root.find("title_block")
        self.title_block = {}
        if tb is not None:
            for child in tb.children():
                if child.name == "comment" and len(child) > 2:
                    self.title_block[f"comment{child[1]}"] = child[2]
                elif len(child) > 1:
                    self.title_block[child.name] = child[1]

    @classmethod
    def load(cls, path) -> "Schematic":
        from .authoring import project_path
        path = project_path(path)
        data = path.read_bytes()
        return cls(parse(data.decode("utf-8")), path=path, source=data)

    @property
    def name(self) -> str:
        return self.path.stem if self.path else self.title_block.get("title", "schematic")

    @property
    def title(self) -> str:
        return self.title_block.get("title", "")

    # structure

    def _lib(self, node: Node) -> Node | None:
        name = node.value("lib_name") or node.value("lib_id", "")
        lib = self.libs.get(name) or self.libs.get(node.value("lib_id", ""))
        return lib

    def _sub_symbols(self, lib: Node) -> list[Node]:
        subs = lib.findall("symbol")
        parent = lib.value("extends")
        if parent:
            prefix = lib[1].split(":")[0] + ":" if ":" in lib[1] else ""
            base = self.libs.get(prefix + parent) or self.libs.get(parent)
            if base is not None:
                subs = base.findall("symbol") + subs
        return subs

    def _unit_count(self, lib: Node | None) -> int:
        if lib is None:
            return 1
        units = set()
        for sub in self._sub_symbols(lib):
            m = re.search(r"_(\d+)_(\d+)$", sub[1])
            if m and int(m.group(1)) > 0:
                units.add(int(m.group(1)))
        return max(units) if units else 1

    @property
    def sheets(self) -> list[tuple[str, str]]:
        """``(name, file)`` of each hierarchical sheet on this one."""
        out = []
        for sheet in self.root.findall("sheet"):
            props = {p[1]: p[2] for p in sheet.findall("property") if len(p) > 2}
            name = props.get("Sheetname") or props.get("Sheet name", "")
            file = props.get("Sheetfile") or props.get("Sheet file", "")
            out.append((name, file))
        return out

    def hierarchy(self) -> list["Schematic"]:
        """This sheet and every sheet below it, each loaded once."""
        out, seen = [self], {self.path.resolve() if self.path else None}
        base = self.path.parent if self.path else Path(".")
        for _, file in self.sheets:
            child = (base / file).resolve()
            if child in seen or not child.exists():
                continue
            seen.add(child)
            for sheet in Schematic.load(child).hierarchy():
                if sheet.path and sheet.path.resolve() not in seen - {child}:
                    out.append(sheet)
        return out

    @property
    def parts(self) -> list[SchematicSymbol]:
        """Placed parts on this sheet and those below: symbols in the BOM, not power flags."""
        import copy
        out, seen = [], set()
        for sheet in self.hierarchy():
            for symbol in sheet.symbols:
                if symbol.power or symbol.reference.startswith("#") or not symbol.in_bom:
                    continue
                # A sheet placed twice puts each of its parts on the board twice.
                for _, reference, unit in symbol.instances or [("", symbol.reference, symbol.unit)]:
                    if reference in seen:
                        continue  # another unit of a part already listed
                    seen.add(reference)
                    part = copy.copy(symbol)
                    part.fields = {**symbol.fields, "Reference": reference}
                    part.unit = unit
                    out.append(part)
        return out

    def __getitem__(self, reference: str) -> SchematicSymbol:
        for s in self.parts:
            if s.reference == reference:
                return s
        raise KeyError(f"no symbol {reference!r}; there are "
                       f"{', '.join(sorted(s.reference for s in self.parts)) or 'none'}")

    def bom(self, *fields: str, titles: dict | None = None, **options):
        """The bill of materials: one row per value and footprint, with quantity.

        Extra ``fields`` (``"MPN"``, ``"Manufacturer"``) become columns. Parts
        marked do-not-populate are listed apart, marked DNP.
        """
        return bom_table([(p.reference, p.value, p.footprint, p.dnp, p.fields) for p in self.parts],
                         fields, titles, **options)

    # drawing

    def drawing(self, *, width: float = 170, caption: str | None = None, colour: bool = True,
                attach: bool = True):
        """The sheet as a vector drawing, cropped to what is drawn on it.

        ``colour=False`` draws everything in ink, for a document printed in black.
        ``attach`` links the schematic file beneath the drawing.
        """
        canvas = self._canvas(COLOURS if colour else MONOCHROME)
        attachments = ({self.path.name: self.source} if attach and self.path and self.source else {})
        return canvas.drawing(width=width, caption=caption, attachments=attachments, margin=1.5)

    def _canvas(self, colours) -> Canvas:
        canvas = Canvas()
        root = self.root
        for item in root.findall("sheet"):
            self._sheet(canvas, item, colours)
        for item in root.findall("rectangle") + root.findall("polyline") + root.findall("circle") \
                + root.findall("arc") + root.findall("bezier"):
            self._graphic(canvas, item, lambda x, y: (x, y), colours["graphic"], colours, sheet=True)
        for wire in root.findall("wire"):
            self._line(canvas, wire, colours["wire"], _LINE)
        for bus in root.findall("bus"):
            self._line(canvas, bus, colours["bus"], 0.305)
        for entry in root.findall("bus_entry"):
            x, y, _ = entry.xy()
            size = entry.find("size")
            dx, dy = (float(size[1]), float(size[2])) if size is not None else (2.54, 2.54)
            canvas.line(x, y, x + dx, y + dy, stroke=colours["wire"], width=_LINE)
        for symbol in self.symbols:
            self._symbol(canvas, symbol, colours)
        for junction in root.findall("junction"):
            x, y, _ = junction.xy()
            d = junction.number("diameter", 0.0) or 0.9144
            canvas.circle(x, y, d / 2, fill=colours["junction"])
        for nc in root.findall("no_connect"):
            x, y, _ = nc.xy()
            for sx in (-1, 1):
                canvas.line(x - 0.635, y - 0.635 * sx, x + 0.635, y + 0.635 * sx,
                            stroke=colours["noconnect"], width=_LINE)
        for label in root.findall("label"):
            self._label(canvas, label, colours["label"])
        for label in root.findall("global_label") + root.findall("hierarchical_label"):
            self._shaped_label(canvas, label, colours)
        for text in root.findall("text"):
            self._note(canvas, text, colours["note"])
        for box in root.findall("text_box"):
            self._text_box(canvas, box, colours)
        return canvas

    @staticmethod
    def _line(canvas, node, colour, default):
        pts = node.find("pts")
        if pts is None:
            return
        points = [(float(p[1]), float(p[2])) for p in pts.findall("xy")]
        width, dash = _stroke(node, default)
        canvas.polyline(points, stroke=colour, width=width, dash=dash)

    def _graphic(self, canvas, item, pt, stroke_colour, colours, *, sheet=False, phase=None):
        """One shape; ``phase="fill"`` paints only a background fill, ``"line"``
        everything but it."""
        width, dash = _stroke(item)
        fill = _fill(item, colours, stroke_colour)
        raw = item.find("stroke")
        stroke = None if raw is not None and raw.number("width", 0.0) < 0 else stroke_colour
        background = item.find("fill") is not None and item.find("fill").value("type") == "background"
        if phase == "fill":
            stroke = None
        elif phase == "line" and background:
            fill = None
        name = item.name
        if name == "polyline":
            pts = item.find("pts")
            points = [pt(float(p[1]), float(p[2])) for p in pts.findall("xy")] if pts is not None else []
            canvas.polyline(points, stroke=stroke, width=width, fill=fill, dash=dash,
                            closed=bool(fill) and len(points) > 2)
        elif name == "rectangle":
            (x1, y1, _), (x2, y2, _) = item.xy("start"), item.xy("end")
            corners = [pt(x1, y1), pt(x2, y1), pt(x2, y2), pt(x1, y2)]
            canvas.polyline(corners, stroke=stroke, width=width, fill=fill, dash=dash, closed=True)
        elif name == "circle":
            cx, cy, _ = item.xy("center")
            r = item.number("radius", 0.0)
            px, py = pt(cx, cy)
            canvas.circle(px, py, r, stroke=stroke, width=width, fill=fill, dash=dash)
        elif name == "arc":
            s, m, e = item.xy("start"), item.xy("mid"), item.xy("end")
            points = _arc_points(pt(s[0], s[1]), pt(m[0], m[1]), pt(e[0], e[1]))
            canvas.polyline(points, stroke=stroke, width=width, fill=fill, dash=dash,
                            closed=bool(fill))
        elif name == "bezier":
            pts = item.find("pts")
            points = [pt(float(p[1]), float(p[2])) for p in pts.findall("xy")] if pts is not None else []
            if len(points) == 4:
                d = "M {:.3f} {:.3f} C {:.3f} {:.3f} {:.3f} {:.3f} {:.3f} {:.3f}".format(
                    *[c for p in points for c in p])
                canvas.path(d, points, stroke=stroke, width=width, fill=fill, dash=dash)

    def _symbol(self, canvas: Canvas, symbol: SchematicSymbol, colours) -> None:
        lib = symbol.lib
        x0, y0 = symbol.at
        m = _matrix(symbol.angle, symbol.mirror)

        def pt(lx, ly):
            return x0 + m[0][0] * lx + m[0][1] * ly, y0 + m[1][0] * lx + m[1][1] * ly

        if lib is None:  # the library graphic is missing: a labelled box
            canvas.rect(x0 - 2.54, y0 - 2.54, 5.08, 5.08, stroke=colours["body"], width=_LINE, dash=(0.6, 0.4))
        else:
            body_style = int(symbol.node.number("convert", 1)) or 1
            hide_numbers = _hidden(lib, "pin_numbers")
            names = lib.find("pin_names")
            hide_names = _hidden(lib, "pin_names")
            offset = names.number("offset", 0.508) if names is not None else 0.508
            subs = self._sub_symbols(lib)
            shapes = []
            for sub in subs:
                mm = re.search(r"_(\d+)_(\d+)$", sub[1])
                unit, style = (int(mm.group(1)), int(mm.group(2))) if mm else (0, 0)
                if unit not in (0, symbol.unit) or style not in (0, body_style):
                    continue
                shapes += [item for item in sub.children()
                           if item.name in ("polyline", "rectangle", "circle", "arc", "bezier")]
            # Body backgrounds first, as KiCad paints them, so they never hide a line.
            for item in shapes:
                if item.find("fill") is not None and item.find("fill").value("type") == "background":
                    self._graphic(canvas, item, pt, colours["body"], colours, phase="fill")
            for item in shapes:
                self._graphic(canvas, item, pt, colours["body"], colours, phase="line")
            for sub in subs:
                mm = re.search(r"_(\d+)_(\d+)$", sub[1])
                unit, style = (int(mm.group(1)), int(mm.group(2))) if mm else (0, 0)
                if unit not in (0, symbol.unit) or style not in (0, body_style):
                    continue
                for item in sub.children():
                    if item.name == "pin":
                        self._pin(canvas, item, pt, m, colours, hide_numbers, hide_names, offset)
                    elif item.name == "text":
                        self._lib_text(canvas, item, pt, m, colours["body"])
        rotated = m[0][1] != 0
        for prop in symbol.node.findall("property"):
            if len(prop) < 3:
                continue
            effects = prop.find("effects")
            h, v, hidden = _justify(effects)
            if hidden or prop.flag("hide"):
                continue
            text = prop[2]
            if prop[1] == "Reference":
                text = symbol.display_reference
            text = symbol.expand(text)
            if not text or text == "~":
                continue
            size, bold, italic = _font(effects)
            fx, fy, fangle = prop.xy()
            # KiCad places a field by the box it would have on the unturned
            # symbol, turned with the symbol, and draws the text centred in it.
            dx, dy = fx - x0, fy - y0
            r = [[m[0][0], -m[0][1]], [m[1][0], -m[1][1]]]  # the turn and mirror alone
            det = r[0][0] * r[1][1] - r[0][1] * r[1][0]
            inv = [[r[1][1] / det, -r[0][1] / det], [-r[1][0] / det, r[0][0] / det]]
            px, py = inv[0][0] * dx + inv[0][1] * dy, inv[1][0] * dx + inv[1][1] * dy
            w = text_width(_plain(text), size * _EM)
            vertical = round(fangle) % 180 == 90
            bx = {"left": w / 2, "center": 0.0, "right": -w / 2}[h]
            by = {"top": size / 2, "center": 0.0, "bottom": -size / 2}[v]
            cx, cy = (px + by, py - bx) if vertical else (px + bx, py + by)
            sx, sy = x0 + r[0][0] * cx + r[0][1] * cy, y0 + r[1][0] * cx + r[1][1] * cy
            angle = 90.0 if vertical != rotated else 0.0
            _text(canvas, sx, sy, text, size, angle=angle, colour=colours["field"], bold=bold,
                  italic=italic)

    def _pin(self, canvas, pin: Node, pt, m, colours, hide_numbers, hide_names, offset):
        if pin.flag("hide"):
            return
        x, y, angle = pin.xy()
        length = pin.number("length", 2.54)
        style = pin[2] if len(pin) > 2 and isinstance(pin[2], str) else "line"
        ux, uy = math.cos(math.radians(angle)), math.sin(math.radians(angle))
        p = pt(x, y)
        q = pt(x + length * ux, y + length * uy)
        dx, dy = (q[0] - p[0]) / (length or 1), (q[1] - p[1]) / (length or 1)
        colour = colours["pin"]
        end = q
        if "inverted" in style:
            r = 0.381
            canvas.circle(q[0] - dx * r, q[1] - dy * r, r, stroke=colour, width=_LINE)
            end = (q[0] - 2 * dx * r, q[1] - 2 * dy * r)
        if length > 0:
            canvas.line(p[0], p[1], end[0], end[1], stroke=colour, width=_LINE)
        if "clock" in style:
            c = 0.635
            canvas.polyline([(q[0] - dy * c, q[1] + dx * c), (q[0] + dx * c, q[1] + dy * c),
                             (q[0] + dy * c, q[1] - dx * c)], stroke=colour, width=_LINE)
        horizontal = abs(dx) > abs(dy)
        name_node, number_node = pin.find("name"), pin.find("number")
        name = name_node[1] if name_node is not None and len(name_node) > 1 else ""
        number = number_node[1] if number_node is not None and len(number_node) > 1 else ""
        mid = ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
        if number and not hide_numbers and length > 0:
            size = _font(number_node.find("effects"))[0] if number_node is not None else 1.27
            size = min(size, 1.27)
            if horizontal:
                _text(canvas, mid[0], mid[1] - 0.3, number, size, valign="bottom",
                      colour=colours["pin_number"])
            else:
                _text(canvas, mid[0] - 0.3, mid[1], number, size, valign="bottom", angle=90,
                      colour=colours["pin_number"])
        if name and name != "~" and not hide_names:
            size = _font(name_node.find("effects"))[0] if name_node is not None else 1.27
            if offset > 0:  # inside the body, beyond the pin's inner end
                nx, ny = q[0] + dx * offset, q[1] + dy * offset
                if horizontal:
                    _text(canvas, nx, ny, name, size, anchor="start" if dx > 0 else "end",
                          colour=colours["pin_name"])
                else:
                    _text(canvas, nx, ny, name, size, anchor="start" if dy < 0 else "end", angle=90,
                          colour=colours["pin_name"])
            elif horizontal:
                _text(canvas, mid[0], mid[1] - 0.3, name, size, valign="bottom", colour=colours["pin_name"])
            else:
                _text(canvas, mid[0] - 0.3, mid[1], name, size, valign="bottom", angle=90,
                      colour=colours["pin_name"])

    def _lib_text(self, canvas, item: Node, pt, m, colour):
        if len(item) < 2:
            return
        x, y, tenths = item.xy()
        effects = item.find("effects")
        h, v, hidden = _justify(effects)
        if hidden:
            return
        size, bold, italic = _font(effects)
        sx, sy = pt(x, y)
        a = math.radians(tenths / 10)
        vx = m[0][0] * math.cos(a) + m[0][1] * math.sin(a)
        vy = m[1][0] * math.cos(a) + m[1][1] * math.sin(a)
        angle = 90.0 if abs(vy) > abs(vx) else 0.0
        _text(canvas, sx, sy, item[1], size, anchor=_ANCHOR[h], valign=_VALIGN[v], angle=angle,
              colour=colour, bold=bold, italic=italic)

    @staticmethod
    def _label(canvas, label: Node, colour):
        x, y, angle = label.xy()
        size, bold, italic = _font(label.find("effects"))
        a = round(angle) % 360
        if a == 0:
            _text(canvas, x, y - 0.3, label[1], size, anchor="start", valign="bottom", colour=colour)
        elif a == 180:
            _text(canvas, x, y - 0.3, label[1], size, anchor="end", valign="bottom", colour=colour)
        elif a == 90:
            _text(canvas, x - 0.3, y, label[1], size, anchor="start", valign="bottom", angle=90, colour=colour)
        else:
            _text(canvas, x - 0.3, y, label[1], size, anchor="end", valign="bottom", angle=90, colour=colour)

    @staticmethod
    def _shaped_label(canvas, label: Node, colours):
        x, y, angle = label.xy()
        size, bold, italic = _font(label.find("effects"))
        shape = label.value("shape", "passive")
        hierarchical = label.name == "hierarchical_label"
        text = label[1]
        w = text_width(_plain(text), size * _EM)
        h = size * 1.6
        a = round(angle) % 360
        colour = colours["global"] if not hierarchical else colours["sheet"]
        # outline along +x from the connection point, then turned into place
        tip = h / 2
        if hierarchical:
            body = [(0, -h / 2), (h, -h / 2), (h, h / 2), (0, h / 2)]
            if shape == "input":
                body = [(0, 0), (h / 2, -h / 2), (h, -h / 2), (h, h / 2), (h / 2, h / 2)]
            elif shape == "output":
                body = [(0, -h / 2), (h / 2, -h / 2), (h, 0), (h / 2, h / 2), (0, h / 2)]
            text_start = h + 0.6
        else:
            left = tip if shape in ("input", "bidirectional", "tri_state") else 0.0
            right_end = left + w + 1.2 + (tip if shape in ("output", "bidirectional", "tri_state") else 0.0)
            body = [(left, -h / 2), (left + w + 1.2, -h / 2)]
            if shape in ("output", "bidirectional", "tri_state"):
                body.append((right_end, 0))
            body += [(left + w + 1.2, h / 2), (left, h / 2)]
            if shape in ("input", "bidirectional", "tri_state"):
                body.append((0, 0))
            text_start = left + 0.6
        direction = {0: 0, 180: 180, 90: 90, 270: 270}.get(a, 0)
        flip = direction  # the body extends the way the text is justified
        c, s = math.cos(math.radians(flip)), -math.sin(math.radians(flip))
        pts = [(x + px * c - py * s, y + px * s + py * c) for px, py in body]
        canvas.polyline(pts, stroke=colour, width=_LINE, closed=True)
        tx, ty = x + (text_start + w / 2) * c, y + (text_start + w / 2) * s
        _text(canvas, tx, ty, text, size, angle=90 if direction in (90, 270) else 0, colour=colour)

    @staticmethod
    def _note(canvas, text: Node, colour):
        x, y, angle = text.xy()
        effects = text.find("effects")
        h, v, hidden = _justify(effects)
        if hidden or len(text) < 2:
            return
        size, bold, italic = _font(effects)
        _text(canvas, x, y, text[1], size, anchor=_ANCHOR[h], valign=_VALIGN[v] if v != "middle" else "bottom",
              angle=90 if round(angle) % 180 == 90 else 0, colour=colour, bold=bold, italic=italic)

    def _text_box(self, canvas, box: Node, colours):
        x, y, _ = box.xy()
        size_node = box.find("size")
        w, h = (float(size_node[1]), float(size_node[2])) if size_node is not None else (10.0, 5.0)
        width, dash = _stroke(box)
        canvas.rect(x, y, w, h, stroke=colours["note"], width=width, dash=dash,
                    fill=_fill(box, colours, colours["note"]))
        size, bold, italic = _font(box.find("effects"))
        _text(canvas, x + 0.8, y + 0.8, box[1], size, anchor="start", valign="top", colour=colours["note"],
              bold=bold, italic=italic)

    def _sheet(self, canvas, sheet: Node, colours):
        x, y, _ = sheet.xy()
        size = sheet.find("size")
        w, h = (float(size[1]), float(size[2])) if size is not None else (20.0, 20.0)
        canvas.rect(x, y, w, h, stroke=colours["sheet"], width=0.2,
                    fill=None if colours["sheet_fill"] == "none" else colours["sheet_fill"])
        for prop in sheet.findall("property"):
            if len(prop) < 3:
                continue
            effects = prop.find("effects")
            hh, vv, hidden = _justify(effects)
            if hidden:
                continue
            fx, fy, fangle = prop.xy()
            fsize, bold, italic = _font(effects)
            text = prop[2] if prop[1] not in ("Sheetfile", "Sheet file") else f"File: {prop[2]}"
            _text(canvas, fx, fy, text, fsize, anchor=_ANCHOR[hh], valign=_VALIGN[vv] if vv != "center" else "bottom",
                  colour=colours["sheet"], angle=90 if round(fangle) % 180 == 90 else 0)
        for pin in sheet.findall("pin"):
            px, py, pangle = pin.xy()
            psize = _font(pin.find("effects"))[0]
            inward = {0: -1, 180: 1}.get(round(pangle) % 360)  # angle 0: on the right edge
            if inward is None:
                _text(canvas, px, py + (1.0 if round(pangle) % 360 == 270 else -1.0), pin[1], psize,
                      angle=90, colour=colours["sheet"])
                continue
            canvas.polyline([(px, py - 0.6), (px + inward * 1.2, py - 0.6), (px + inward * 1.2, py + 0.6),
                             (px, py + 0.6)], stroke=colours["sheet"], width=_LINE, closed=True)
            _text(canvas, px + inward * 1.8, py, pin[1], psize, anchor="end" if inward < 0 else "start",
                  colour=colours["sheet"])

    # kip hooks

    def kip_content(self, kind: str):
        if kind == "table":
            return self.bom()
        if kind == "draw":
            return self.drawing()
        return self

    def kip_summary(self) -> str:
        parts = self.parts
        return (f"schematic {self.name}: {len(parts)} parts, {len(self.sheets)} sub-sheets"
                + (f", {self.title!r}" if self.title else ""))


def bom_table(parts, fields=(), titles=None, **options):
    """A bill of materials from ``(reference, value, footprint, dnp, fields)`` rows:
    one row per value and footprint, the references collapsed into ranges."""
    from .content import Column, Table
    groups: dict[tuple, list[str]] = defaultdict(list)
    for reference, value, footprint, dnp, extra in parts:
        key = (value, footprint, dnp, *(str(extra.get(f, "")) for f in fields))
        groups[key].append(reference)
    titles = titles or {}
    rows = []
    for key, refs in sorted(groups.items(), key=lambda kv: min(_ref_key(r) for r in kv[1])):
        value, footprint, dnp, *extra = key
        rows.append((reference_ranges(refs), len(refs), value + (" (DNP)" if dnp else ""),
                     footprint.split(":")[-1], *extra))
    columns = [Column("refs", "References"), Column("qty", "Qty"), Column("value", "Value"),
               Column("footprint", "Footprint")]
    columns += [Column(f, titles.get(f, f)) for f in fields]
    return Table(columns, rows, **options)


def _hidden(lib: Node, name: str) -> bool:
    node = lib.find(name)
    return node is not None and node.flag("hide")


def _ref_key(ref: str):
    m = re.match(r"([A-Za-z#_]*)(\d*)", ref)
    return (m.group(1), int(m.group(2) or 0)) if m else (ref, 0)

# -- xschem -------------------------------------------------------------------------

_XS_COLOURS = {1: "#2b7a3b", 2: "#2a4f9e", 3: "#8a1c1c", 4: "#8a1c1c", 5: "#8a1c1c", 6: "#6b3fa0",
               7: "#8a1c1c", 8: "#0d5c63", 9: "#2a4f9e", 10: "#8a6a12", 11: "#6b3fa0", 12: "#0d5c63"}


def _xs_records(text: str) -> list[tuple[str, list[str], str]]:
    """xschem's records: a letter, its fields, and the ``{...}`` property string.

    Braces nest and backslash-escape, so the text is walked, not split."""
    out = []
    i, n = 0, len(text)
    while i < n:
        while i < n and text[i] in " \t\r\n":
            i += 1
        if i >= n:
            break
        kind = text[i]
        i += 1
        fields: list[str] = []
        prop = ""
        while i < n and text[i] != "\n" or (fields and fields[-1] == "\x00"):
            if text[i] in " \t\r":
                i += 1
                continue
            if text[i] == "{":
                depth, j = 1, i + 1
                while j < n and depth:
                    if text[j] == "\\":
                        j += 2
                        continue
                    depth += {"{": 1, "}": -1}.get(text[j], 0)
                    j += 1
                block = text[i + 1:j - 1]
                i = j
                if kind in "CT" and not fields:
                    fields.append(block)
                else:
                    prop = block
                continue
            j = i
            while j < n and text[j] not in " \t\r\n{":
                j += 1
            fields.append(text[i:j])
            i = j
        out.append((kind, fields, prop))
    return out


def _xs_props(prop: str) -> dict[str, str]:
    out = {}
    for m in re.finditer(r'(\w+)\s*=\s*("(?:[^"\\]|\\.)*"|\S+)', prop):
        out[m.group(1)] = m.group(2).strip('"')
    return out


def _xs_rotate(x, y, rot, flip):
    if flip:
        x = -x
    rot %= 4
    if rot == 1:
        return -y, x
    if rot == 2:
        return -x, -y
    if rot == 3:
        return y, -x
    return x, y


def _xs_text(canvas, x, y, text, *, cap, turn, mirrored, hcenter, vcenter, colour):
    """xschem text: it hangs below and runs right of its anchor, turned and flipped
    with its symbol, and is always drawn to read left to right or bottom to top."""
    em = cap / 0.73
    lines = text.split("\n")
    pitch = cap * 1.45
    block = cap + (len(lines) - 1) * pitch
    top = -block / 2 if vcenter else 0.0  # where the block starts, along its downward side
    for k, line in enumerate(lines):
        first = cap + k * pitch
        if turn in (0, 2):
            forward = (turn == 0) != mirrored
            anchor = "middle" if hcenter else ("start" if forward else "end")
            baseline = y + top + first if turn == 0 else y - top - block + first
            canvas.text(x, baseline, line, size=em, anchor=anchor, fill=colour)
        else:
            downward = (turn == 1) != mirrored  # it runs down the page, before being made readable
            anchor = "middle" if hcenter else ("end" if downward else "start")
            baseline = x - top - block + first if turn == 1 else x + top + first
            canvas.text(baseline, y, line, size=em, anchor=anchor, angle=90, fill=colour)


#: Stand-ins for xschem's basic devices, drawn when its library is not installed.
#: Their pins are where the library's are, so wires still meet them.
_XS_STANDIN = {
    "res.sym": """L 4 0 -30 0 -20 {}
L 4 0 20 0 30 {}
B 4 -5 -20 5 20 {}
B 5 -2.5 -32.5 2.5 -27.5 {name=P}
B 5 -2.5 27.5 2.5 32.5 {name=M}
T {@name} 10 -17.5 0 0 0.2 0.2 {}
T {@value} 10 -2.5 0 0 0.2 0.2 {}""",
    "capa.sym": """L 4 0 -30 0 -5 {}
L 4 0 5 0 30 {}
L 4 -10 -5 10 -5 {}
L 4 -10 5 10 5 {}
B 5 -2.5 -32.5 2.5 -27.5 {name=p}
B 5 -2.5 27.5 2.5 32.5 {name=m}
T {@name} 15 -17.5 0 0 0.2 0.2 {}
T {@value} 15 -2.5 0 0 0.2 0.2 {}""",
    "ind.sym": """L 4 0 -30 0 -20 {}
L 4 0 20 0 30 {}
A 4 0 -15 5 270 180 {}
A 4 0 -5 5 270 180 {}
A 4 0 5 5 270 180 {}
A 4 0 15 5 270 180 {}
B 5 -2.5 -32.5 2.5 -27.5 {name=p}
B 5 -2.5 27.5 2.5 32.5 {name=m}
T {@name} 15 -17.5 0 0 0.2 0.2 {}
T {@value} 15 -2.5 0 0 0.2 0.2 {}""",
    "vsource.sym": """L 4 0 -30 0 -15 {}
L 4 0 15 0 30 {}
A 4 0 0 15 0 360 {}
L 4 0 -10 0 -4 {}
L 4 -3 -7 3 -7 {}
L 4 -3 7 3 7 {}
B 5 -2.5 -32.5 2.5 -27.5 {name=p}
B 5 -2.5 27.5 2.5 32.5 {name=m}
T {@name} 20 -17.5 0 0 0.2 0.2 {}
T {@value} 20 -2.5 0 0 0.2 0.2 {}""",
    "isource.sym": """L 4 0 -30 0 -15 {}
L 4 0 15 0 30 {}
A 4 0 0 15 0 360 {}
L 4 0 -8 0 8 {}
L 4 0 8 -3 3 {}
L 4 0 8 3 3 {}
B 5 -2.5 -32.5 2.5 -27.5 {name=p}
B 5 -2.5 27.5 2.5 32.5 {name=m}
T {@name} 20 -17.5 0 0 0.2 0.2 {}
T {@value} 20 -2.5 0 0 0.2 0.2 {}""",
    "gnd.sym": """L 4 0 0 0 10 {}
L 4 -10 10 10 10 {}
L 4 -6 14 6 14 {}
L 4 -2 18 2 18 {}
B 5 -2.5 -2.5 2.5 2.5 {name=p}""",
    "vdd.sym": """L 4 0 -10 0 0 {}
L 4 -10 -10 10 -10 {}
B 5 -2.5 -2.5 2.5 2.5 {name=p}
T {@lab} -12.5 -25 0 0 0.2 0.2 {}""",
    "lab_pin.sym": """B 5 -2.5 -2.5 2.5 2.5 {name=p}
T {@lab} -2.5 -10 0 1 0.2 0.2 {}""",
    "lab_wire.sym": """B 5 -2.5 -2.5 2.5 2.5 {name=p}
T {@lab} 2.5 -10 0 0 0.2 0.2 {}""",
    "ipin.sym": """P 5 6 -20 -5 -10 -5 -5 0 -10 5 -20 5 -20 -5 {}
L 4 -5 0 0 0 {}
B 5 -2.5 -2.5 2.5 2.5 {name=p}
T {@lab} -25 -4 0 1 0.2 0.2 {}""",
    "opin.sym": """P 5 6 5 -5 15 -5 20 0 15 5 5 5 5 -5 {}
L 4 0 0 5 0 {}
B 5 -2.5 -2.5 2.5 2.5 {name=p}
T {@lab} 25 -4 0 0 0.2 0.2 {}""",
    "iopin.sym": """P 5 7 5 0 10 -5 20 -5 25 0 20 5 10 5 5 0 {}
L 4 0 0 5 0 {}
B 5 -2.5 -2.5 2.5 2.5 {name=p}
T {@lab} 30 -4 0 0 0.2 0.2 {}""",
    "nmos4.sym": """L 4 5 -20 5 20 {}
L 4 -20 0 -2.5 0 {}
L 4 -2.5 -15 -2.5 15 {}
L 4 5 -20 20 -20 {}
L 4 20 -30 20 -20 {}
L 4 5 20 20 20 {}
L 4 20 20 20 30 {}
L 4 5 0 20 0 {}
P 4 4 10 15 15 20 10 25 10 15 {fill=true}
B 5 17.5 -32.5 22.5 -27.5 {name=D}
B 5 -22.5 -2.5 -17.5 2.5 {name=G}
B 5 17.5 27.5 22.5 32.5 {name=S}
B 5 17.5 -2.5 22.5 2.5 {name=B}
T {@name} 25 -17.5 0 0 0.2 0.2 {}
T {@model} 25 -5 0 0 0.2 0.2 {}""",
    "pmos4.sym": """L 4 5 -20 5 20 {}
L 4 -20 0 -7.5 0 {}
A 4 -5 0 2.5 0 360 {}
L 4 -2.5 -15 -2.5 15 {}
L 4 5 -20 20 -20 {}
L 4 20 -30 20 -20 {}
L 4 5 20 20 20 {}
L 4 20 20 20 30 {}
L 4 5 0 20 0 {}
P 4 4 15 -25 10 -20 15 -15 15 -25 {fill=true}
B 5 17.5 -32.5 22.5 -27.5 {name=S}
B 5 -22.5 -2.5 -17.5 2.5 {name=G}
B 5 17.5 27.5 22.5 32.5 {name=D}
B 5 17.5 -2.5 22.5 2.5 {name=B}
T {@name} 25 -17.5 0 0 0.2 0.2 {}
T {@model} 25 -5 0 0 0.2 0.2 {}""",
    "diode.sym": """L 4 0 -30 0 -10 {}
L 4 0 10 0 30 {}
P 4 4 -10 -10 10 -10 0 10 -10 -10 {fill=true}
L 4 -10 10 10 10 {}
B 5 -2.5 -32.5 2.5 -27.5 {name=p}
B 5 -2.5 27.5 2.5 32.5 {name=m}
T {@name} 15 -17.5 0 0 0.2 0.2 {}
T {@model} 15 -2.5 0 0 0.2 0.2 {}""",
    "npn.sym": """L 4 -20 0 0 0 {}
L 4 0 -15 0 15 {}
L 4 0 -7.5 20 -20 {}
L 4 20 -20 20 -30 {}
L 4 0 7.5 20 20 {}
L 4 20 20 20 30 {}
P 4 4 20 20 12 18 16 13 20 20 {fill=true}
B 5 17.5 -32.5 22.5 -27.5 {name=C}
B 5 -22.5 -2.5 -17.5 2.5 {name=B}
B 5 17.5 27.5 22.5 32.5 {name=E}
T {@name} 25 -17.5 0 0 0.2 0.2 {}
T {@model} 25 -5 0 0 0.2 0.2 {}""",
    "pnp.sym": """L 4 -20 0 0 0 {}
L 4 0 -15 0 15 {}
L 4 0 -7.5 20 -20 {}
L 4 20 -20 20 -30 {}
L 4 0 7.5 20 20 {}
L 4 20 20 20 30 {}
P 4 4 0 7.5 8 10 4 14 0 7.5 {fill=true}
B 5 17.5 -32.5 22.5 -27.5 {name=E}
B 5 -22.5 -2.5 -17.5 2.5 {name=B}
B 5 17.5 27.5 22.5 32.5 {name=C}
T {@name} 25 -17.5 0 0 0.2 0.2 {}
T {@model} 25 -5 0 0 0.2 0.2 {}""",
    "noconn.sym": """L 4 -5 -5 5 5 {}
L 4 -5 5 5 -5 {}
B 5 -2.5 -2.5 2.5 2.5 {name=p}""",
}
_XS_STANDIN.update({"nmos.sym": _XS_STANDIN["nmos4.sym"], "pmos.sym": _XS_STANDIN["pmos4.sym"],
                    "nmos3.sym": _XS_STANDIN["nmos4.sym"], "pmos3.sym": _XS_STANDIN["pmos4.sym"]})


def _xschem_paths(base: Path | None) -> list[Path]:
    paths = []
    if base is not None:
        paths.append(base)
    for var in ("XSCHEM_LIBRARY_PATH",):
        for part in os.environ.get(var, "").split(os.pathsep):
            if part:
                paths.append(Path(part))
    pdk = os.environ.get("PDK_ROOT")
    if pdk:
        for name in ("sky130A", "gf180mcuD", "gf180mcuC", "ihp-sg13g2"):
            paths.append(Path(pdk) / name / "libs.tech" / "xschem")
    for root in ("/usr/share/xschem/xschem_library", "/usr/local/share/xschem/xschem_library"):
        for sub in ("", "devices"):
            paths.append(Path(root) / sub)
    return [p for p in paths if p.is_dir()]


class XSchematic:
    """An xschem schematic (``.sch``): its components, wires, labels and text.

    Symbols are read from ``.sym`` files beside the schematic and on the
    xschem library path (``XSCHEM_LIBRARY_PATH``, and ``PDK_ROOT``'s PDKs); a
    symbol that cannot be found is drawn as a labelled box, and listed in
    :attr:`missing`.
    """

    def __init__(self, text: str, *, path: Path | None = None, source: bytes | None = None,
                 library: list | None = None):
        self.path, self.source = path, source
        self.records = _xs_records(text)
        self.library = [Path(p) for p in (library or [])] + _xschem_paths(path.parent if path else None)
        self.components = []
        for kind, fields, prop in self.records:
            if kind == "C" and len(fields) >= 5:
                props = _xs_props(prop)
                self.components.append({"symbol": fields[0], "x": float(fields[1]), "y": float(fields[2]),
                                        "rot": int(float(fields[3])), "flip": int(float(fields[4])),
                                        "props": props, "name": props.get("name", "")})
        self._symbols: dict[str, list | None] = {}
        #: Symbols that were not found (drawn as boxes), and those drawn from kip's stand-ins.
        self.missing: list[str] = []
        self.standins: list[str] = []

    @classmethod
    def load(cls, path, *, library=None) -> "XSchematic":
        from .authoring import project_path
        path = project_path(path)
        data = path.read_bytes()
        return cls(data.decode("utf-8", errors="replace"), path=path, source=data, library=library)

    @property
    def name(self) -> str:
        return self.path.stem if self.path else "schematic"

    def _symbol(self, ref: str):
        if ref in self._symbols:
            return self._symbols[ref]
        found = None
        for base in self.library:
            for candidate in (base / ref, base / Path(ref).name):
                if candidate.is_file():
                    found = _xs_records(candidate.read_text(encoding="utf-8", errors="replace"))
                    break
            if found is not None:
                break
        if found is None and Path(ref).name in _XS_STANDIN:
            found = _xs_records(_XS_STANDIN[Path(ref).name])
            self.standins.append(ref)
        if found is None:
            self.missing.append(ref)
        self._symbols[ref] = found
        return found

    @property
    def parts(self) -> list[dict]:
        """Components that are devices: not pins, labels, grounds or text."""
        skip = ("lab_pin", "lab_wire", "ipin", "opin", "iopin", "gnd", "vdd", "title", "code", "launcher",
                "noconn", "architecture", "netlist")
        return [c for c in self.components if not any(Path(c["symbol"]).stem.startswith(s) for s in skip)]

    def table(self, **options):
        """The components: name, symbol, and value."""
        from .content import Column, Table
        rows = []
        for c in self.parts:
            p = c["props"]
            value = p.get("value") or " ".join(f"{k}={p[k]}" for k in ("W", "L", "nf", "mult", "m")
                                              if k in p) or p.get("model", "")
            rows.append((c["name"], Path(c["symbol"]).stem, value))
        return Table([Column("name", "Name"), Column("symbol", "Symbol"), Column("value", "Value")],
                     rows, **options)

    def drawing(self, *, width: float = 170, caption: str | None = None, attach: bool = True):
        """The schematic as a vector drawing (an xschem unit drawn as 0.1 mm)."""
        canvas = Canvas()
        scale = 0.1
        self.missing, self.standins = [], []
        self._symbols.clear()
        self._draw_records(canvas, self.records, lambda x, y: (x * scale, y * scale), {}, top=True)
        for c in self.components:
            records = self._symbol(c["symbol"])

            def pt(x, y, c=c):
                rx, ry = _xs_rotate(x, y, c["rot"], c["flip"])
                return (c["x"] + rx) * scale, (c["y"] + ry) * scale
            if records is None:
                x, y = pt(0, 0)
                canvas.rect(x - 2, y - 2, 4, 4, stroke=_XS_COLOURS[4], width=0.15, dash=(0.6, 0.4))
                canvas.text(x, y + 3.2, Path(c["symbol"]).stem, size=1.4, anchor="middle", fill=_XS_COLOURS[4])
                continue
            self._draw_records(canvas, records, pt, c["props"], rot=c["rot"], flip=c["flip"])
        attachments = ({self.path.name: self.source} if attach and self.path and self.source else {})
        return canvas.drawing(width=width, caption=caption, attachments=attachments, margin=1.5)

    def _draw_records(self, canvas, records, pt, props, *, rot=0, flip=0, top=False):
        for kind, fields, prop in records:
            try:
                self._draw_record(canvas, kind, fields, prop, pt, props, rot, flip, top)
            except (ValueError, IndexError):
                continue  # a record this reader does not draw

    @staticmethod
    def _draw_record(canvas, kind, fields, prop, pt, props, rot, flip, top):
        width = 0.2
        if kind == "N" and len(fields) >= 4:
            (x1, y1), (x2, y2) = pt(float(fields[0]), float(fields[1])), pt(float(fields[2]), float(fields[3]))
            canvas.line(x1, y1, x2, y2, stroke=_XS_COLOURS[1], width=width)
        elif kind == "L" and len(fields) >= 5:
            layer = int(fields[0])
            (x1, y1), (x2, y2) = pt(float(fields[1]), float(fields[2])), pt(float(fields[3]), float(fields[4]))
            dash = (0.6, 0.4) if "dash" in prop else None
            canvas.line(x1, y1, x2, y2, stroke=_XS_COLOURS.get(layer, INK), width=width, dash=dash)
        elif kind == "B" and len(fields) >= 5:
            layer = int(fields[0])
            (x1, y1), (x2, y2) = pt(float(fields[1]), float(fields[2])), pt(float(fields[3]), float(fields[4]))
            colour = _XS_COLOURS.get(layer, INK)
            x, y, w, h = min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1)
            if layer == 5 and not top:  # a pin: a small filled square
                canvas.rect(x, y, w, h, fill=colour)
            else:
                full = "fill=full" in prop or "fill=true" in prop
                canvas.rect(x, y, w, h, stroke=colour, width=width, fill=colour if full else None,
                            opacity=0.35 if full else None)
        elif kind == "P" and len(fields) >= 2:
            layer, count = int(fields[0]), int(fields[1])
            coords = [float(v) for v in fields[2:2 + 2 * count]]
            points = [pt(coords[k], coords[k + 1]) for k in range(0, len(coords) - 1, 2)]
            colour = _XS_COLOURS.get(layer, INK)
            filled = "fill=true" in prop or "fill=full" in prop
            canvas.polyline(points, stroke=colour, width=width, fill=colour if filled else None,
                            closed=filled)
        elif kind == "A" and len(fields) >= 6:
            layer = int(fields[0])
            cx, cy, r, a0, sweep = (float(v) for v in fields[1:6])
            points = [pt(cx + r * math.cos(math.radians(a0 + sweep * k / 24)),
                         cy - r * math.sin(math.radians(a0 + sweep * k / 24))) for k in range(25)]
            colour = _XS_COLOURS.get(layer, INK)
            canvas.polyline(points, stroke=colour, width=width,
                            fill=colour if "fill=true" in prop else None)
        elif kind == "T" and len(fields) >= 7:
            text = re.sub(r"@(\w+)", lambda m: props.get(m.group(1), ""), fields[0])
            text = text.replace("\\{", "{").replace("\\}", "}")
            if not text.strip() or text.startswith("tcleval"):
                return
            x, y = pt(float(fields[1]), float(fields[2]))
            tp = _xs_props(prop)
            layer = int(tp["layer"]) if tp.get("layer", "").isdigit() else (8 if top else 4)
            _xs_text(canvas, x, y, text, cap=float(fields[6]) * 30 * 0.1,
                     turn=(int(float(fields[3])) + rot) % 4, mirrored=(int(float(fields[4])) + flip) % 2 == 1,
                     hcenter=tp.get("hcenter") == "true", vcenter=tp.get("vcenter") == "true",
                     colour=_XS_COLOURS.get(layer, INK))

    def kip_content(self, kind: str):
        if kind == "table":
            return self.table()
        if kind == "draw":
            return self.drawing()
        return self

    def kip_summary(self) -> str:
        return f"xschem schematic {self.name}: {len(self.parts)} devices, {len(self.components)} components"


# -- KiCad netlists and SKiDL ----------------------------------------------------------


class KicadNetlist:
    """The parts and nets of a circuit: a KiCad netlist (``.net``) -- what
    Eeschema, ``kicad-cli sch export netlist`` and SKiDL's ``generate_netlist()``
    write -- or a SKiDL circuit itself.

    ``net.parts`` are dictionaries (``ref``, ``value``, ``footprint`` and the
    part's fields); ``net.nets`` maps each net to its ``(ref, pin)`` nodes.
    A table cell shows its bill of materials; :meth:`nets_table` lists the nets.
    """

    def __init__(self, parts: list[dict], nets: dict[str, list[tuple[str, str, str]]], *, name: str = "",
                 source: str = ""):
        self.parts, self.nets, self.name, self.source = parts, nets, name, source

    @classmethod
    def parse(cls, text: str, *, name: str = "") -> "KicadNetlist":
        root = parse(text)
        if root.name != "export":
            raise ValueError("not a KiCad netlist (it does not start with (export ...))")
        parts = []
        components = root.find("components")
        for comp in components.findall("comp") if components is not None else []:
            fields = {}
            holder = comp.find("fields")
            for f in holder.findall("field") if holder is not None else []:
                fname = f.value("name")
                if fname:
                    fields[fname] = f[2] if len(f) > 2 and isinstance(f[2], str) else ""
            for prop in comp.findall("property"):
                if prop.value("name"):
                    fields.setdefault(prop.value("name"), prop.value("value", ""))
            parts.append({"ref": comp.value("ref", "?"), "value": comp.value("value", ""),
                          "footprint": comp.value("footprint", ""), "datasheet": comp.value("datasheet", ""),
                          "description": comp.value("description", ""),
                          "dnp": "dnp" in fields or fields.get("dnp") == "1", **fields})
        nets: dict[str, list[tuple[str, str, str]]] = {}
        holder = root.find("nets")
        for net in holder.findall("net") if holder is not None else []:
            nets[net.value("name", net.value("code", "?"))] = [
                (node.value("ref", "?"), node.value("pin", "?"), node.value("pinfunction", "") or "")
                for node in net.findall("node")]
        return cls(parts, nets, name=name, source=text)

    @classmethod
    def load(cls, path) -> "KicadNetlist":
        from .authoring import project_path
        path = project_path(path)
        return cls.parse(path.read_text(encoding="utf-8", errors="replace"), name=path.stem)

    def __getitem__(self, ref: str) -> dict:
        for part in self.parts:
            if part["ref"] == ref:
                return part
        raise KeyError(f"no part {ref!r}; there are {', '.join(p['ref'] for p in self.parts)}")

    def net(self, name: str) -> list[tuple[str, str, str]]:
        """The ``(ref, pin, function)`` nodes on net ``name`` (``/out`` or ``out``)."""
        for key in (name, "/" + name.lstrip("/")):
            if key in self.nets:
                return self.nets[key]
        raise KeyError(f"no net {name!r}")

    def connections(self, ref: str) -> dict[str, str]:
        """Each pin of part ``ref`` and the net it is on."""
        return {pin: net for net, nodes in self.nets.items() for r, pin, _ in nodes if r == ref}

    def bom(self, *fields: str, titles: dict | None = None, **options):
        return bom_table([(p["ref"], p["value"], p["footprint"], p["dnp"], p) for p in self.parts],
                         fields, titles, **options)

    def nets_table(self, **options):
        """Every net with the pins it joins, ``R1.2`` for pin 2 of R1."""
        from .content import Column, Table
        rows = [(name.lstrip("/") or name, len(nodes), ", ".join(f"{r}.{p}" for r, p, _ in
                                                                  sorted(nodes, key=lambda n: (_ref_key(n[0]), n[1]))))
                for name, nodes in sorted(self.nets.items(), key=lambda kv: kv[0].lower())]
        return Table([Column("net", "Net"), Column("count", "Pins"), Column("nodes", "Connections")],
                     rows, **options)

    def kip_content(self, kind: str):
        return self.bom() if kind == "table" else self

    def kip_summary(self) -> str:
        return f"netlist {self.name}: {len(self.parts)} parts, {len(self.nets)} nets"


def from_skidl(circuit=None) -> KicadNetlist:
    """A SKiDL circuit's parts and nets (by default SKiDL's ``default_circuit``).

    kip calls this for a SKiDL circuit in a table cell; nothing is written to
    disk, unlike ``generate_netlist()``.
    """
    if circuit is None:
        import builtins
        import skidl
        circuit = getattr(skidl, "default_circuit", None) or getattr(builtins, "default_circuit", None)
        if circuit is None:
            raise ValueError("SKiDL has no default circuit; pass the circuit")
    parts = []
    for part in getattr(circuit, "parts", []):
        fields = {k: str(v) for k, v in (getattr(part, "fields", None) or {}).items()}
        parts.append({"ref": str(getattr(part, "ref", "?")), "value": str(getattr(part, "value", "") or ""),
                      "footprint": str(getattr(part, "footprint", "") or ""),
                      "description": str(getattr(part, "description", "") or ""),
                      "dnp": bool(getattr(part, "dnp", False)), **fields})
    nets: dict[str, list[tuple[str, str, str]]] = {}
    raw_nets = circuit.get_nets() if hasattr(circuit, "get_nets") else getattr(circuit, "nets", [])
    for net in raw_nets:
        pins = net.get_pins() if hasattr(net, "get_pins") else getattr(net, "pins", [])
        nodes = [(str(getattr(getattr(pin, "part", None), "ref", "?")), str(getattr(pin, "num", "?")),
                  str(getattr(pin, "name", "") or "")) for pin in pins]
        if nodes:
            nets.setdefault(str(getattr(net, "name", "?")), []).extend(nodes)
    return KicadNetlist(parts, nets, name=str(getattr(circuit, "name", "") or "circuit"))


def read_schematic(path, **options):
    """A schematic file: KiCad (``.kicad_sch``) or xschem (``.sch``)."""
    from .authoring import project_path
    resolved = project_path(path)
    if resolved.suffix.lower() == ".kicad_sch":
        return Schematic.load(resolved)
    head = resolved.read_bytes()[:200].lstrip()
    if head.startswith(b"(kicad_sch"):
        return Schematic.load(resolved)
    if head.startswith(b"v {xschem") or resolved.suffix.lower() == ".sch":
        return XSchematic.load(resolved, **options)
    raise ValueError(f"{resolved.name}: not a KiCad or xschem schematic")


# -- schemdraw ----------------------------------------------------------------------


def from_schemdraw(drawing, *, width: float | None = None, caption: str | None = None):
    """A schemdraw drawing as a kip :class:`~kip.Drawing`, its text in kip's fonts.

    kip calls this for a draw cell whose last expression is a schemdraw
    drawing; call it to set the width or caption.
    """
    from .content import Drawing
    # schemdraw's own SVG canvas: transparent, and its text stays text
    figure = drawing.draw(show=False, canvas="svg")
    svg = figure.getimage(ext="svg")
    drawing.fig = None  # leave the drawing to draw on its usual canvas again
    if isinstance(svg, str):
        svg = svg.encode("utf-8")
    family = MONO.encode()
    svg = re.sub(rb'font-family="[^"]*"', b'font-family="' + family + b'"', svg)
    svg = re.sub(rb"font-family:[^;\"']*", b"font-family:" + family, svg)
    m = re.search(rb"<svg[^>]*\bwidth=['\"]([\d.]+)(pt|px)?['\"]", svg)
    natural = float(m.group(1)) * (25.4 / 72 if (m.group(2) or b"pt") == b"pt" else 25.4 / 96) if m else 100.0
    return Drawing(svg=svg, width=min(width, natural) if width else natural, caption=caption)
