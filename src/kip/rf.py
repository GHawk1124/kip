"""RF and electromagnetics: S-parameters, Smith charts, antenna patterns, openEMS models.

- :func:`read_touchstone` reads a Touchstone file (``.s1p``, ``.s2p``, ``.sNp``;
  versions 1 and 2) -- what VNAs, openEMS, HFSS, Sonnet, ADS and scikit-rf
  write -- into a :class:`Network`. ``net.s11`` is a :class:`~kip.spice.Signal`,
  so ``plot(net.s11)`` draws its return loss and ``net.resonance()``,
  ``net.bandwidth()`` and ``net.vswr().at(f)`` measure it.
- :func:`smith_chart` draws reflection coefficients on a Smith chart; a draw
  cell whose last expression is a network shows its S11 there.
- :func:`polar_pattern` draws antenna radiation patterns in dB.
- :func:`read_csx` reads an openEMS/CSXCAD model (``CSX.Write2XML``): its
  metals, materials, ports and mesh, drawn in plan or section.
"""
from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from .spice import Signal, _engineering
from .svg import FAINT, INK, MONO, SERIF, Canvas
from .units import fmt_quantity, ureg

__all__ = ["Network", "read_touchstone", "smith_chart", "polar_pattern", "Geometry", "read_csx"]

TRACES = ("#c0392b", "#2e5fb8", "#2c9a63", "#c9a227", "#8e44ad", "#d35400")

# -- Touchstone -----------------------------------------------------------------------

_FREQ = {"hz": 1.0, "khz": 1e3, "mhz": 1e6, "ghz": 1e9, "thz": 1e12}


class Network:
    """An N-port's S-parameters against frequency.

    ``net.s21`` (or ``net.s_param(2, 1)``) is a complex :class:`~kip.spice.Signal`;
    ``net.f`` the frequencies, ``net.s`` the matrices, ``net.z0`` the reference impedance.
    """

    def __init__(self, f, s, *, z0: float = 50.0, name: str = "", path: Path | None = None):
        import numpy as np
        self.f = ureg.Quantity(np.asarray(f, dtype=float), "Hz")
        self.s = np.asarray(s, dtype=complex)
        self.z0, self.name, self.path = float(z0), name, path

    @property
    def ports(self) -> int:
        return self.s.shape[1]

    def __len__(self) -> int:
        return len(self.s)

    def s_param(self, i: int, j: int) -> Signal:
        if not (1 <= i <= self.ports and 1 <= j <= self.ports):
            raise ValueError(f"S{i}{j}: this is a {self.ports}-port network")
        return Signal(self.f, ureg.Quantity(self.s[:, i - 1, j - 1], "dimensionless"), name=f"S{i}{j}",
                      xname="frequency")

    def __getattr__(self, name: str):
        m = re.fullmatch(r"s(\d)(\d)", name)
        if m:
            return self.s_param(int(m.group(1)), int(m.group(2)))
        raise AttributeError(name)

    def gamma(self, port: int = 1) -> Signal:
        return self.s_param(port, port)

    def return_loss(self, port: int = 1) -> Signal:
        """-20·log10|Sii|: the return loss in dB, positive."""
        rl = -self.gamma(port).db()
        rl.name = f"RL{port}"
        return rl

    def vswr(self, port: int = 1) -> Signal:
        import numpy as np
        g = np.abs(self.s[:, port - 1, port - 1])
        return Signal(self.f, ureg.Quantity((1 + g) / np.maximum(1e-12, 1 - g), "dimensionless"),
                      name=f"VSWR{port}", xname="frequency")

    def impedance(self, port: int = 1) -> Signal:
        """The input impedance seen at ``port``, Z0·(1 + Γ)/(1 − Γ)."""
        g = self.s[:, port - 1, port - 1]
        return Signal(self.f, ureg.Quantity(self.z0 * (1 + g) / (1 - g), "ohm"), name=f"Z{port}",
                      xname="frequency")

    def resonance(self, port: int = 1):
        """The frequency of the best match: the minimum of |Sii|."""
        import numpy as np
        k = int(np.argmin(np.abs(self.s[:, port - 1, port - 1])))
        return _engineering(self.f[k])

    def band(self, port: int = 1, level: float = -10.0) -> tuple:
        """The frequencies either side of the resonance where |Sii| crosses ``level`` dB."""
        import numpy as np
        g = 20 * np.log10(np.maximum(np.abs(self.s[:, port - 1, port - 1]), 1e-15))
        f = self.f.magnitude
        k = int(np.argmin(g))
        if g[k] >= level:
            raise ValueError(f"S{port}{port} never falls below {level:g} dB")
        lo = k
        while lo > 0 and g[lo - 1] < level:
            lo -= 1
        hi = k
        while hi < len(g) - 1 and g[hi + 1] < level:
            hi += 1
        if lo == 0 or hi == len(g) - 1:
            raise ValueError(f"S{port}{port} is below {level:g} dB at the edge of the sweep; widen it")
        f_lo = f[lo - 1] + (level - g[lo - 1]) * (f[lo] - f[lo - 1]) / (g[lo] - g[lo - 1])
        f_hi = f[hi] + (level - g[hi]) * (f[hi + 1] - f[hi]) / (g[hi + 1] - g[hi])
        return _engineering(ureg.Quantity(float(f_lo), "Hz")), _engineering(ureg.Quantity(float(f_hi), "Hz"))

    def bandwidth(self, port: int = 1, level: float = -10.0):
        """The impedance bandwidth: the width of the band where |Sii| < ``level`` dB."""
        lo, hi = self.band(port, level)
        return _engineering((hi - lo).to("Hz"))

    def group_delay(self, i: int = 2, j: int = 1) -> Signal:
        import numpy as np
        phase = np.unwrap(np.angle(self.s[:, i - 1, j - 1]))
        w = 2 * np.pi * self.f.magnitude
        return Signal(self.f, ureg.Quantity(-np.gradient(phase, w), "s"), name=f"τ{i}{j}", xname="frequency")

    def plot(self, *params: str, **options):
        """|S| in dB against frequency, every parameter (or those named, ``"s11"``)."""
        from .content import Figure
        names = list(params) or [f"s{i}{j}" for i in range(1, self.ports + 1) for j in range(1, self.ports + 1)
                                 if self.ports <= 2 or i == j or j == 1]
        f = _engineering(self.f)
        fig = Figure(xlabel="Frequency", ylabel="|S| (dB)", **options)
        for n in names:
            sig = getattr(self, n.lower())
            fig.line(f, sig.db().y.magnitude, label=n.upper())
        return fig

    def smith(self, port: int = 1, **options):
        options.setdefault("z0", self.z0)
        return smith_chart(self.gamma(port), **options)

    def kip_content(self, kind: str):
        if kind == "plot":
            return self.plot()
        if kind == "draw":
            return self.smith(markers=[self.resonance()])
        return self

    def kip_summary(self) -> str:
        f0, f1 = _engineering(self.f[0]), _engineering(self.f[-1])
        text = f"{self.ports}-port network {self.name}: {len(self)} points, {fmt_quantity(f0)} to {fmt_quantity(f1)}"
        try:
            return text + f", best match at {fmt_quantity(self.resonance())}"
        except ValueError:
            return text


def read_touchstone(path) -> Network:
    """A Touchstone file (version 1 or 2): ``.s1p``, ``.s2p``, ... ``.sNp``."""
    import numpy as np
    from .authoring import project_path
    path = project_path(path)
    text = path.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"\.s(\d+)p$", path.name, re.I)
    ports = int(m.group(1)) if m else None
    unit, param, fmt, z0 = "ghz", "s", "ma", 50.0
    order_12_21 = False
    numbers: list[float] = []
    in_data = True
    version2 = False
    for raw in text.splitlines():
        line = raw.split("!", 1)[0].strip()
        if not line:
            continue
        if line.startswith("#"):
            words = line[1:].lower().split()
            k = 0
            while k < len(words):
                w = words[k]
                if w in _FREQ:
                    unit = w
                elif w in ("s", "y", "z", "h", "g"):
                    param = w
                elif w in ("ma", "db", "ri"):
                    fmt = w
                elif w == "r" and k + 1 < len(words):
                    z0 = float(words[k + 1])
                    k += 1
                k += 1
            continue
        if line.startswith("["):
            key = line.lower()
            version2 = True
            if key.startswith("[number of ports]"):
                ports = int(line.split("]")[1])
            elif key.startswith("[two-port data order]"):
                order_12_21 = "12_21" in key
            elif key.startswith("[reference]"):
                values = line.split("]")[1].split()
                if values:
                    z0 = float(values[0])
            elif key.startswith("[noise data]") or key.startswith("[end]"):
                in_data = False
            elif key.startswith("[network data]"):
                in_data = True
            continue
        if in_data:
            numbers.extend(float(v) for v in line.split())
    if ports is None:
        raise ValueError(f"{path.name}: the number of ports is not known (name the file .sNp)")
    per = 1 + 2 * ports * ports
    rows = []
    k = 0
    last_f = -1.0
    while k + per <= len(numbers):
        row = numbers[k:k + per]
        if row[0] <= last_f and ports == 2:  # noise parameters follow the network data
            break
        last_f = row[0]
        rows.append(row)
        k += per
    if not rows:
        raise ValueError(f"{path.name}: no network data")
    data = np.array(rows)
    f = data[:, 0] * _FREQ[unit]
    a, b = data[:, 1::2], data[:, 2::2]
    if fmt == "ri":
        values = a + 1j * b
    elif fmt == "ma":
        values = a * np.exp(1j * np.radians(b))
    else:
        values = 10 ** (a / 20) * np.exp(1j * np.radians(b))
    matrix = values.reshape(len(f), ports, ports)
    if ports == 2 and not (version2 and order_12_21):
        matrix = matrix.transpose(0, 2, 1)  # a 2-port is listed S11 S21 S12 S22
    if param in ("z", "y"):
        eye = np.eye(ports)
        # version 1 normalises Z and Y to the reference impedance; version 2 does not
        if param == "z":
            zn = matrix if not version2 else matrix / z0
        else:
            zn = np.linalg.inv(matrix if not version2 else matrix * z0)
        matrix = np.array([(m - eye) @ np.linalg.inv(m + eye) for m in zn])
    elif param != "s":
        raise ValueError(f"{path.name}: {param.upper()}-parameters are not supported; export S-parameters")
    return Network(f, matrix, z0=z0, name=path.stem, path=path)

# -- Smith chart -------------------------------------------------------------------------


def _gamma(z: complex) -> complex:
    return (z - 1) / (z + 1)


def smith_chart(*traces, markers=None, labels=None, width: float = 100, caption: str | None = None,
                admittance: bool = False, z0: float = 50.0):
    """Reflection coefficients on a Smith chart.

    ``traces`` are complex signals (``net.s11``) or networks (their S11).
    ``markers`` are frequencies to mark and label with the impedance there.
    """
    import numpy as np
    canvas = Canvas()
    R = 40.0

    def xy(g: complex):
        return R * g.real, -R * g.imag

    canvas.circle(0, 0, R, fill="#fdfbf4", stroke=INK, width=0.35)
    grid = "#cbbfa6"
    for r in (0.2, 0.5, 1.0, 2.0, 5.0):
        pts = [xy(_gamma(complex(r, math.tan(t)))) for t in np.linspace(-math.pi / 2 + 1e-3, math.pi / 2 - 1e-3, 181)]
        canvas.polyline(pts, stroke=grid, width=0.2)
        gx, gy = xy(_gamma(complex(r, 0)))
        canvas.text(gx - 0.6, gy - 0.7, f"{r:g}", size=1.9, anchor="end", fill=FAINT)
    for x in (0.2, 0.5, 1.0, 2.0, 5.0):
        for sign in (1, -1):
            ts = np.concatenate([np.linspace(0, 0.98, 120), [0.995, 0.999]])
            pts = [xy(_gamma(complex(t / (1 - t), sign * x))) for t in ts]
            canvas.polyline(pts, stroke=grid, width=0.2)
            gx, gy = xy(_gamma(complex(0, sign * x)))
            canvas.text(gx * 1.07, gy * 1.07, f"{'+' if sign > 0 else '−'}j{x:g}", size=1.9, anchor="middle",
                        middle=True, fill=FAINT)
    canvas.line(-R, 0, R, 0, stroke=grid, width=0.2)
    if admittance:
        for r in (0.5, 1.0, 2.0):
            pts = [xy(-_gamma(complex(r, math.tan(t)))) for t in np.linspace(-math.pi / 2 + 1e-3, math.pi / 2 - 1e-3, 181)]
            canvas.polyline(pts, stroke="#d8c9e8", width=0.2, dash=(0.8, 0.5))
    legend = []
    for k, trace in enumerate(traces):
        if isinstance(trace, Network):
            trace = trace.gamma(1)
        colour = TRACES[k % len(TRACES)]
        values = np.asarray(trace.y.magnitude, dtype=complex)
        canvas.polyline([xy(g) for g in values], stroke=colour, width=0.45)
        name = (labels[k] if labels and k < len(labels) else trace.name) or f"trace {k + 1}"
        legend.append((colour, name))
        for f in markers or []:
            g = trace.at(f).magnitude
            g = complex(g)
            px, py = xy(g)
            canvas.circle(px, py, 0.8, fill=colour, stroke="#fdfbf4", width=0.25)
            z = z0 * (1 + g) / (1 - g) if g != 1 else complex("inf")
            text = f"{fmt_quantity(_engineering(f.to('Hz') if isinstance(f, ureg.Quantity) else ureg.Quantity(f, 'Hz')))}"
            text += f"  {z.real:.1f}{'+' if z.imag >= 0 else '−'}j{abs(z.imag):.1f} Ω"
            canvas.text(px + 1.4, py - 1.2, text, size=2.0, fill=colour)
    lx, ly = -R, R + 6.0
    for colour, name in legend:
        canvas.rect(lx, ly - 2.1, 2.4, 2.4, fill=colour, rx=0.3)
        canvas.text(lx + 3.2, ly, name, size=2.8, fill="#3a342b", font=SERIF)
        lx += 3.2 + 1.4 * len(name) + 4
    return canvas.drawing(width=width, caption=caption, margin=1.5)

# -- radiation patterns -----------------------------------------------------------------


def polar_pattern(angles, *gains, labels=None, floor: float | None = None, step: float = 10.0,
                  width: float = 90, caption: str | None = None, unit: str = "dBi"):
    """Radiation patterns on a polar grid, 0° at the top and angles clockwise.

    ``polar_pattern(theta, gain_E, gain_H, labels=["E-plane", "H-plane"])``:
    ``angles`` in degrees (or a quantity), each gain in dB. Rings every
    ``step`` dB from the peak down to ``floor`` (30 dB below it by default).
    """
    import numpy as np
    if isinstance(angles, ureg.Quantity):
        angles = angles.to("degree").magnitude
    angles = np.asarray(angles, dtype=float)
    series = [np.asarray(g.magnitude if isinstance(g, ureg.Quantity) else g, dtype=float) for g in gains]
    if not series:
        raise ValueError("polar_pattern needs at least one gain")
    peak = max(float(np.nanmax(s)) for s in series)
    top = math.ceil(peak / step) * step
    bottom = floor if floor is not None else top - 3 * step
    R = 35.0
    canvas = Canvas()

    def radius(db):
        return R * (np.clip(db, bottom, top) - bottom) / (top - bottom)

    canvas.circle(0, 0, R, fill="#fdfbf4", stroke=INK, width=0.35)
    level = top - step
    while level > bottom + 1e-9:
        canvas.circle(0, 0, float(radius(level)), stroke="#cbbfa6", width=0.2)
        level -= step
    for a in range(0, 360, 30):
        rad = math.radians(a)
        canvas.line(0, 0, R * math.sin(rad), -R * math.cos(rad), stroke="#cbbfa6", width=0.2)
        canvas.text(1.09 * R * math.sin(rad), -1.09 * R * math.cos(rad), f"{a}°", size=2.0, anchor="middle",
                    middle=True, fill=FAINT)
    level = top
    while level >= bottom - 1e-9:
        r = float(radius(level))
        canvas.text(0.8, -r + 2.4, f"{level:g} {unit}" if level == top else f"{level:g}", size=1.8, fill=FAINT)
        level -= step
    legend = []
    for k, s in enumerate(series):
        colour = TRACES[k % len(TRACES)]
        r = radius(s)
        pts = [(float(ri * math.sin(math.radians(a))), float(-ri * math.cos(math.radians(a))))
               for a, ri in zip(angles, r) if np.isfinite(ri)]
        canvas.polyline(pts, stroke=colour, width=0.45)
        legend.append((colour, labels[k] if labels and k < len(labels) else f"pattern {k + 1}"))
    lx, ly = -R, R + 7.0
    for colour, name in legend:
        canvas.rect(lx, ly - 2.1, 2.4, 2.4, fill=colour, rx=0.3)
        canvas.text(lx + 3.2, ly, name, size=2.8, fill="#3a342b", font=SERIF)
        lx += 3.2 + 1.4 * len(name) + 4
    return canvas.drawing(width=width, caption=caption, margin=1.5)

# -- openEMS / CSXCAD ------------------------------------------------------------------------

_PROPERTY_COLOURS = {"metal": "#c9a24a", "conductingsheet": "#c9a24a", "material": "#9cc7a4",
                     "lumpedelement": "#c0392b", "excitation": "#d35400", "probebox": "#2e5fb8",
                     "dumpbox": "#8e44ad"}


def _attr(el: ET.Element, *names, default=None):
    for name in names:
        for key, value in el.attrib.items():
            if key.lower() == name.lower():
                return value
        child = next((c for c in el if c.tag.lower() == name.lower()), None)
        if child is not None and child.text:
            return child.text.strip()
    return default


def _num(text, default=0.0) -> float:
    try:
        return float(text)
    except (TypeError, ValueError):
        return default


def _point(el: ET.Element | None):
    if el is None:
        return None
    return tuple(_num(_attr(el, axis)) for axis in ("X", "Y", "Z"))


class Primitive:
    """One CSXCAD shape: a box, polygon, extruded polygon, cylinder, sphere or curve,
    in drawing units."""

    def __init__(self, el: ET.Element, prop: "Property"):
        self.kind = el.tag
        self.property = prop
        self.priority = int(_num(_attr(el, "Priority"), 0))
        self.el = el

    def bounds(self):
        """((x0, y0, z0), (x1, y1, z1)) of the shape, in drawing units."""
        corners = []
        for plane in ("xy", "xz"):
            pts, _ = self.outline(plane)
            corners.append(pts)
        xy, xz = corners
        if not xy or not xz:
            return None
        xs = [p[0] for p in xy + xz]
        ys = [p[1] for p in xy]
        zs = [p[1] for p in xz]
        return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))

    def outline(self, plane: str):
        """The shape projected on ``plane`` ("xy", "xz" or "yz") as (points, closed)."""
        axes = {"xy": (0, 1), "xz": (0, 2), "yz": (1, 2)}[plane]
        kind = self.kind.lower()
        el = self.el
        if kind == "box":
            p1, p2 = _point(el.find("P1")), _point(el.find("P2"))
            if p1 is None or p2 is None:
                return [], True
            a0, a1 = sorted((p1[axes[0]], p2[axes[0]]))
            b0, b1 = sorted((p1[axes[1]], p2[axes[1]]))
            return [(a0, b0), (a1, b0), (a1, b1), (a0, b1)], True
        if kind in ("polygon", "linpoly", "rotpoly"):
            norm = int(_num(_attr(el, "NormDir"), 2))
            elev = _num(_attr(el, "Elevation"), 0.0)
            length = _num(_attr(el, "Length"), 0.0)
            # the vertex coordinates are the two axes other than the normal, in order
            others = [a for a in range(3) if a != norm]
            pts3 = []
            for v in el.findall("Vertex"):
                p = [0.0, 0.0, 0.0]
                p[others[0]], p[others[1]], p[norm] = _num(_attr(v, "X1")), _num(_attr(v, "X2")), elev
                pts3.append(p)
            if not pts3:
                return [], True
            if norm not in axes:
                return [(p[axes[0]], p[axes[1]]) for p in pts3], True
            # seen edge on: the polygon (and its extrusion) is a band
            along = [a for a in axes if a != norm][0]
            lo, hi = min(p[along] for p in pts3), max(p[along] for p in pts3)
            n0, n1 = sorted((elev, elev + length))
            if axes[0] == norm:
                return [(n0, lo), (n1, lo), (n1, hi), (n0, hi)], True
            return [(lo, n0), (hi, n0), (hi, n1), (lo, n1)], True
        if kind in ("cylinder", "cylindricalshell"):
            p1, p2 = _point(el.find("P1")), _point(el.find("P2"))
            r = _num(_attr(el, "Radius"))
            if p1 is None or p2 is None:
                return [], True
            axis = max(range(3), key=lambda a: abs(p2[a] - p1[a]))
            if axis not in axes:
                cx, cy = p1[axes[0]], p1[axes[1]]
                return [(cx + r * math.cos(t * math.pi / 24), cy + r * math.sin(t * math.pi / 24)) for t in range(48)], True
            other = [a for a in axes if a != axis][0]
            c = p1[other]
            a0, a1 = sorted((p1[axis], p2[axis]))
            if axes[0] == axis:
                return [(a0, c - r), (a1, c - r), (a1, c + r), (a0, c + r)], True
            return [(c - r, a0), (c + r, a0), (c + r, a1), (c - r, a1)], True
        if kind == "sphere":
            c = _point(el.find("Center"))
            r = _num(_attr(el, "Radius"))
            if c is None:
                return [], True
            return [(c[axes[0]] + r * math.cos(t * math.pi / 24), c[axes[1]] + r * math.sin(t * math.pi / 24))
                    for t in range(48)], True
        if kind in ("curve", "wire"):
            pts = [_point(v) for v in el.findall("Vertex")]
            return [(p[axes[0]], p[axes[1]]) for p in pts if p], False
        return [], True


class Property:
    """A CSXCAD property -- metal, material, lumped element, excitation, probe -- and its shapes."""

    def __init__(self, el: ET.Element):
        self.kind = el.tag
        self.name = _attr(el, "Name", default="")
        self.attributes = dict(el.attrib)
        prop = el.find("Property")
        if prop is not None:
            self.attributes.update(prop.attrib)
        holder = el.find("Primitives")
        self.primitives = [Primitive(p, self) for p in (holder if holder is not None else [])]

    @property
    def epsilon(self) -> float | None:
        value = _attr(ET.Element("x", self.attributes), "Epsilon")
        return _num(value) if value is not None else None

    @property
    def kappa(self) -> float | None:
        value = _attr(ET.Element("x", self.attributes), "Kappa")
        return _num(value) if value is not None else None


class Geometry:
    """An openEMS model as CSXCAD writes it: properties with their shapes, the mesh,
    and the FDTD settings.

    ``geo.size`` is the simulation domain; ``geo.cells`` the mesh cell count;
    :meth:`drawing` a plan (``plane="xy"``) or a section (``"xz"``, ``"yz"``),
    with the mesh lines if ``mesh=True``.
    """

    def __init__(self, root: ET.Element, *, name: str = "", path: Path | None = None):
        struct = root if root.tag == "ContinuousStructure" else root.find(".//ContinuousStructure")
        if struct is None:
            raise ValueError("not a CSXCAD model: no <ContinuousStructure>")
        self.name, self.path = name, path
        props = struct.find("Properties")
        self.properties = [Property(p) for p in (props if props is not None else [])]
        grid = struct.find("RectilinearGrid")
        self.unit = _num(_attr(grid, "DeltaUnit"), 1.0) if grid is not None else 1.0
        self.lines = []
        for axis in ("XLines", "YLines", "ZLines"):
            el = grid.find(axis) if grid is not None else None
            text = el.text if el is not None and el.text else ""
            self.lines.append(sorted(_num(v) for v in re.split(r"[,\s]+", text.strip()) if v))
        fdtd = root.find(".//FDTD")
        self.fdtd = dict(fdtd.attrib) if fdtd is not None else {}
        exc = fdtd.find("Excitation") if fdtd is not None else None
        self.excitation = dict(exc.attrib) if exc is not None else {}
        bc = fdtd.find("BoundaryCond") if fdtd is not None else None
        self.boundaries = dict(bc.attrib) if bc is not None else {}

    @classmethod
    def load(cls, path) -> "Geometry":
        from .authoring import project_path
        path = project_path(path)
        return cls(ET.parse(path).getroot(), name=path.stem, path=path)

    def __getitem__(self, name: str) -> Property:
        for p in self.properties:
            if p.name == name:
                return p
        raise KeyError(f"no property {name!r}; there are {', '.join(p.name for p in self.properties)}")

    def _q(self, value):
        return _engineering_length(value * self.unit)

    @property
    def size(self) -> tuple:
        """The simulation domain: the extent of the mesh in x, y and z."""
        return tuple(self._q(l[-1] - l[0]) if l else self._q(0.0) for l in self.lines)

    @property
    def cells(self) -> int:
        n = 1
        for l in self.lines:
            n *= max(1, len(l) - 1)
        return n

    @property
    def smallest_cell(self):
        steps = [b - a for l in self.lines for a, b in zip(l, l[1:]) if b > a]
        return self._q(min(steps)) if steps else None

    @property
    def largest_cell(self):
        steps = [b - a for l in self.lines for a, b in zip(l, l[1:]) if b > a]
        return self._q(max(steps)) if steps else None

    def materials_table(self, **options):
        """Each property: its kind, relative permittivity and conductivity."""
        from .content import Column, Table
        rows = []
        for p in self.properties:
            eps = p.epsilon
            kappa = p.kappa
            rows.append((p.name, p.kind, f"{eps:g}" if eps is not None else "–",
                         f"{kappa:g}" if kappa is not None else "–", len(p.primitives)))
        return Table([Column("name", "Name"), Column("kind", "Kind"), Column("eps", "εr", align="right"),
                      Column("kappa", "κ (S/m)", align="right"), Column("shapes", "Shapes", align="right")],
                     rows, **options)

    def mesh_table(self, **options):
        from .content import Column, Table
        rows = []
        for axis, l in zip("xyz", self.lines):
            steps = [b - a for a, b in zip(l, l[1:])]
            rows.append((axis, len(l), fmt_quantity(self._q(l[-1] - l[0])) if l else "–",
                         fmt_quantity(self._q(min(steps))) if steps else "–",
                         fmt_quantity(self._q(max(steps))) if steps else "–"))
        return Table([Column("axis", "Axis"), Column("lines", "Lines"), Column("extent", "Extent"),
                      Column("min", "Smallest cell"), Column("max", "Largest cell")], rows, **options)

    def drawing(self, *, plane: str = "xy", mesh: bool = False, region: str = "domain", width: float = 120,
                caption: str | None = None, attach: bool = True):
        """The model in plan (``"xy"``, seen from above) or section (``"xz"``, ``"yz"``),
        shapes coloured by kind, the nearest drawn over the rest.

        ``region="model"`` frames the structure rather than the whole simulation
        domain; ``mesh=True`` draws the mesh lines.
        """
        if plane not in ("xy", "xz", "yz"):
            raise ValueError("plane is 'xy', 'xz' or 'yz'")
        if region not in ("domain", "model"):
            raise ValueError("region is 'domain' or 'model'")
        axes = {"xy": (0, 1), "xz": (0, 2), "yz": (1, 2)}[plane]
        # the viewer looks down z, along +y, or along -x: nearer shapes are drawn last
        normal, sign = {"xy": (2, 1), "xz": (1, -1), "yz": (0, 1)}[plane]

        def depth(prim):
            b = prim.bounds()
            if b is None:
                return 0.0
            return b[1][normal] if sign > 0 else -b[0][normal]

        shapes = [(depth(prim), prim.priority, k, prim) for k, p in enumerate(self.properties)
                  for prim in p.primitives]
        shapes.sort(key=lambda s: s[:3])
        points = []
        for *_, prim in shapes:
            if region == "model" and prim.property.kind.lower() in ("probebox", "dumpbox"):
                continue
            pts, _ = prim.outline(plane)
            points += pts
        lines = [self.lines[axes[0]], self.lines[axes[1]]]
        if region == "domain" and lines[0] and lines[1]:
            points += [(lines[0][0], lines[1][0]), (lines[0][-1], lines[1][-1])]
        if not points:
            raise ValueError("this model has nothing to draw")
        x0, y0 = min(p[0] for p in points), min(p[1] for p in points)
        x1, y1 = max(p[0] for p in points), max(p[1] for p in points)
        if region == "model":
            pad = 0.08 * max(x1 - x0, y1 - y0)
            x0, y0, x1, y1 = x0 - pad, y0 - pad, x1 + pad, y1 + pad
            lines = [[v for v in lines[0] if x0 <= v <= x1], [v for v in lines[1] if y0 <= v <= y1]]
        span = max(x1 - x0, y1 - y0) or 1.0
        scale = 80.0 / span
        canvas = Canvas()

        def to(p):
            return (p[0] - x0) * scale, (y1 - p[1]) * scale

        if region == "model":
            canvas.rect(0, 0, (x1 - x0) * scale, (y1 - y0) * scale, fill="#fdfbf4")
            if mesh:
                for x in lines[0]:
                    canvas.line(to((x, 0))[0], 0, to((x, 0))[0], (y1 - y0) * scale, stroke="#ddd0b0", width=0.08)
                for y in lines[1]:
                    canvas.line(0, to((0, y))[1], (x1 - x0) * scale, to((0, y))[1], stroke="#ddd0b0", width=0.08)
        if region == "domain" and lines[0] and lines[1]:
            (ax, ay), (bx, by) = to((lines[0][0], lines[1][-1])), to((lines[0][-1], lines[1][0]))
            canvas.rect(ax, ay, bx - ax, by - ay, stroke=FAINT, width=0.25, dash=(1.0, 0.6), fill="#fdfbf4")
            if mesh:
                for x in lines[0]:
                    (px, _), (_, qy) = to((x, lines[1][0])), to((x, lines[1][-1]))
                    canvas.line(px, ay, px, by, stroke="#ddd0b0", width=0.08)
                for y in lines[1]:
                    (_, py) = to((lines[0][0], y))
                    canvas.line(ax, py, bx, py, stroke="#ddd0b0", width=0.08)
        legend = {}
        for *_, prim in shapes:
            if region == "model" and prim.property.kind.lower() in ("probebox", "dumpbox"):
                continue
            pts, closed = prim.outline(plane)
            if not pts:
                continue
            kind = prim.property.kind.lower()
            colour = _PROPERTY_COLOURS.get(kind, "#7f8c8d")
            q = [to(p) for p in pts]
            if kind in ("probebox", "dumpbox"):
                canvas.polyline(q, stroke=colour, width=0.25, dash=(0.6, 0.4), closed=closed)
            elif kind in ("lumpedelement", "excitation"):
                canvas.polyline(q, stroke=colour, width=0.5, fill=colour, opacity=0.8, closed=closed)
            elif kind == "material":
                canvas.polyline(q, stroke="#6f9a78", width=0.2, fill=colour, opacity=0.9, closed=closed)
            else:
                canvas.polyline(q, stroke="#8d6f2a", width=0.2, fill=colour if closed else None, closed=closed)
            legend.setdefault(prim.property.name, colour)
        bx0, by0, bx1, by1 = canvas.bounds
        lx, ly = bx0, by1 + 4.0
        for name, colour in legend.items():
            step = 3.2 + 1.4 * len(name) + 4
            if lx > bx0 and lx + step > bx0 + max(80.0, bx1 - bx0):
                lx, ly = bx0, ly + 4.0
            canvas.rect(lx, ly - 2.1, 2.4, 2.4, fill=colour, rx=0.3)
            canvas.text(lx + 3.2, ly, name, size=2.8, fill="#3a342b", font=SERIF)
            lx += step
        size = _engineering_length(span * self.unit)
        canvas.text(bx0, by0 - 2.0, f"{plane} plane, {fmt_quantity(size)} across", size=2.2, fill=FAINT, font=SERIF)
        attachments = {}
        if attach and self.path is not None:
            attachments[self.path.name] = self.path.read_bytes()
        return canvas.drawing(width=width, caption=caption, attachments=attachments, margin=1.5)

    def kip_content(self, kind: str):
        if kind == "draw":
            return self.drawing()
        if kind == "table":
            return self.materials_table()
        return self

    def kip_summary(self) -> str:
        size = " × ".join(fmt_quantity(s) for s in self.size)
        return f"openEMS model {self.name}: {len(self.properties)} properties, {self.cells} mesh cells, {size}"


def _engineering_length(metres: float):
    q = ureg.Quantity(metres, "m")
    for unit, limit in (("m", 1.0), ("mm", 1e-3), ("um", 1e-6), ("nm", 1e-9)):
        if abs(metres) >= limit * 0.9995:
            return q.to(unit)
    return q.to("nm")


def read_csx(path) -> Geometry:
    """An openEMS model written with ``CSX.Write2XML("model.xml")``."""
    return Geometry.load(path)
