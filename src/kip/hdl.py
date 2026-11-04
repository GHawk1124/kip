"""Digital design: HDL modules, waveforms, timing diagrams, and FPGA reports.

- :func:`read_hdl` reads the modules of a Verilog, SystemVerilog or VHDL file:
  their parameters and ports, with the comment beside each port as its
  description. A draw cell shows a module as a block symbol; a table cell
  lists its ports.
- :func:`read_vcd` reads a simulator's value-change dump (Icarus, Verilator,
  GHDL, ModelSim, cocotb) into a :class:`Trace`; :meth:`Trace.timing` draws
  its signals as a timing diagram, and each signal measures its edges,
  period and duty cycle.
- :func:`wavedrom` draws a WaveDrom timing diagram from its JSON.
- :func:`read_utilization` and :func:`read_timing` read what synthesis and
  place-and-route report -- Vivado, Quartus, Yosys, nextpnr, OpenSTA -- and
  :func:`read_constraints` reads pin and clock constraints (XDC, PCF, LPF,
  QSF, CST, SDC).
"""
from __future__ import annotations

import ast
import json
import math
import operator
import re
from dataclasses import dataclass, field
from pathlib import Path

from .svg import FAINT, INK, MONO, SERIF, Canvas, text_width
from .units import fmt_quantity, ureg

__all__ = ["Port", "Module", "read_hdl", "Trace", "Wave", "read_vcd", "wavedrom", "timing_diagram",
           "Utilization", "read_utilization", "TimingReport", "read_timing", "Constraints",
           "read_constraints"]

_ACCENT = "#125f63"
_BUS = "#2a4f9e"

# -- expressions --------------------------------------------------------------------------


def _clog2(x):
    return max(0, math.ceil(math.log2(x))) if x > 0 else 0


def _evaluate(text: str, names: dict):
    """An HDL constant expression, with parameters, or None if it cannot be known."""
    expr = text.strip()
    if not expr:
        return None
    expr = re.sub(r"\$clog2", "clog2", expr)
    expr = re.sub(r"(\d+)?'[sS]?([bBoOdDhH])([0-9a-fA-F_xXzZ]+)",
                  lambda m: str(int(m.group(3).replace("_", ""), {"b": 2, "o": 8, "d": 10, "h": 16}[m.group(2).lower()]))
                  if not re.search(r"[xXzZ]", m.group(3)) else "0", expr)
    expr = expr.replace("**", "^^").replace("/", "//").replace("^^", "**")
    ops = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.FloorDiv: operator.floordiv,
           ast.Mod: operator.mod, ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos,
           ast.LShift: operator.lshift, ast.RShift: operator.rshift}

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.Name):
            value = names.get(node.id, names.get(node.id.lower()))
            if isinstance(value, (int, float)):
                return value
            raise ValueError(node.id)
        if isinstance(node, ast.BinOp) and type(node.op) in ops:
            return ops[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in ops:
            return ops[type(node.op)](ev(node.operand))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "clog2":
            return _clog2(ev(node.args[0]))
        raise ValueError("unsupported")
    try:
        return ev(ast.parse(expr, mode="eval"))
    except (SyntaxError, ValueError, ZeroDivisionError, TypeError, KeyError):
        return None

# -- modules ----------------------------------------------------------------------------


@dataclass
class Port:
    """One port: its name, direction, type, width in bits, and description."""

    name: str
    direction: str            # "in", "out" or "inout"
    type: str = ""
    width: int | None = 1     # None when it depends on a parameter kip cannot evaluate
    range: str = ""           # "[7:0]", "(7 downto 0)"
    description: str = ""

    @property
    def bus(self) -> bool:
        return self.width is None or self.width > 1


@dataclass
class Module:
    """A Verilog/SystemVerilog module or a VHDL entity."""

    name: str
    ports: list[Port] = field(default_factory=list)
    parameters: dict[str, str] = field(default_factory=dict)
    language: str = "verilog"
    description: str = ""
    path: Path | None = None

    def __getitem__(self, name: str) -> Port:
        for p in self.ports:
            if p.name == name or p.name.lower() == name.lower():
                return p
        raise KeyError(f"module {self.name} has no port {name!r}")

    def parameter(self, name: str):
        """A parameter's default as a number (``CLK_HZ = 12_000_000`` is 12000000), or
        its text when it is not a constant kip can evaluate."""
        values: dict = {}
        for k, v in self.parameters.items():
            values[k] = _evaluate(v, values)
        for k, v in self.parameters.items():
            if k == name or k.lower() == name.lower():
                return values[k] if values[k] is not None else v
        raise KeyError(f"module {self.name} has no parameter {name!r}; "
                       f"there are {', '.join(self.parameters) or 'none'}")

    @property
    def inputs(self) -> list[Port]:
        return [p for p in self.ports if p.direction == "in"]

    @property
    def outputs(self) -> list[Port]:
        return [p for p in self.ports if p.direction == "out"]

    @property
    def io_bits(self) -> int | None:
        """Total bits through the ports, None if a width is unknown."""
        if any(p.width is None for p in self.ports):
            return None
        return sum(p.width for p in self.ports)

    def table(self, **options):
        """The ports: name, direction, width, type and description."""
        from .content import Column, Table
        rows = [(p.name, {"in": "input", "out": "output"}.get(p.direction, p.direction),
                 p.width if p.width is not None else p.range, p.type, p.description) for p in self.ports]
        columns = [Column("name", "Port"), Column("dir", "Direction"), Column("width", "Width", align="right"),
                   Column("type", "Type"), Column("description", "Description")]
        if not any(r[4] for r in rows):
            columns, rows = columns[:4], [r[:4] for r in rows]
        if not any(r[3] for r in rows):
            columns, rows = columns[:3] + columns[4:], [r[:3] + r[4:] for r in rows]
        return Table(columns, rows, **options)

    def symbol(self, *, width: float | None = None, caption: str | None = None, parameters: bool = True):
        """The module as a block: inputs on the left, outputs and inouts on the right,
        buses marked with their width, clocks with a wedge."""
        canvas = Canvas()
        size = 2.4          # em, mm
        pitch = 4.0
        stub = 6.0
        left = self.inputs
        right = [p for p in self.ports if p.direction != "in"]
        cw = text_width("M", size)
        lw = max((len(p.name) for p in left), default=0) * cw
        rw = max((len(p.name) for p in right), default=0) * cw
        params = [f"{k} = {v}" for k, v in self.parameters.items()] if parameters else []
        title_w = text_width(self.name, size * 1.15)
        body_w = max(lw + rw + 8.0, title_w + 6.0, max((text_width(t, size * 0.8) for t in params), default=0) + 6)
        head = 7.0 + 3.2 * len(params)
        rows = max(len(left), len(right), 1)
        body_h = head + rows * pitch + 1.0
        x0, y0 = stub, 0.0
        canvas.rect(x0, y0, body_w, body_h, stroke=INK, width=0.35, fill="#fdfbf4")
        canvas.text(x0 + body_w / 2, y0 + 4.6, self.name, size=size * 1.15, anchor="middle", weight="bold")
        for k, text in enumerate(params):
            canvas.text(x0 + body_w / 2, y0 + 8.2 + 3.2 * k, text, size=size * 0.8, anchor="middle", fill=FAINT)
        if params:
            canvas.line(x0, y0 + head - 1.2, x0 + body_w, y0 + head - 1.2, stroke="#cbbfa6", width=0.2)

        def pin(p: Port, y: float, side: int):
            edge = x0 if side < 0 else x0 + body_w
            end = edge + side * stub
            weight = 0.6 if p.bus else 0.3
            colour = _BUS if p.bus else INK
            canvas.line(edge, y, end, y, stroke=colour, width=weight)
            label_x = edge - side * 1.5
            if re.search(r"(^|_)(clk|clock)(_|$)|clk$", p.name, re.I) and side < 0:
                canvas.polyline([(edge, y - 1.1), (edge + 1.6, y), (edge, y + 1.1)], stroke=INK, width=0.3)
                label_x = edge + 2.3
            if re.search(r"(_n|_b|_l)$", p.name, re.I):
                canvas.circle(edge + side * 0.7, y, 0.7, stroke=INK, width=0.3, fill="#fdfbf4")
            canvas.text(label_x, y, p.name, size=size, anchor="start" if side < 0 else "end", middle=True)
            if p.bus:
                mid = (edge + end) / 2
                canvas.line(mid - 0.9, y + 1.2, mid + 0.9, y - 1.2, stroke=colour, width=0.3)
                label = str(p.width) if p.width is not None else p.range
                canvas.text(mid, y - 1.6, label, size=size * 0.75, anchor="middle", fill=colour)

        for k, p in enumerate(left):
            pin(p, y0 + head + pitch * (k + 0.5), -1)
        for k, p in enumerate(right):
            pin(p, y0 + head + pitch * (k + 0.5), 1)
        return canvas.drawing(width=width, caption=caption, margin=1.0)

    def kip_content(self, kind: str):
        if kind == "table":
            return self.table()
        if kind == "draw":
            return self.symbol()
        return self

    def kip_summary(self) -> str:
        return (f"{self.language} module {self.name}: {len(self.inputs)} inputs, {len(self.outputs)} outputs, "
                f"{len(self.ports) - len(self.inputs) - len(self.outputs)} inouts, "
                f"{len(self.parameters)} parameters")


class Modules(list):
    """The modules of an HDL file, by position or by name."""

    def __getitem__(self, key):
        if isinstance(key, str):
            for m in self:
                if m.name == key or m.name.lower() == key.lower():
                    return m
            raise KeyError(f"no module {key!r}; there are {', '.join(m.name for m in self)}")
        return super().__getitem__(key)

    def kip_content(self, kind: str):
        return self[0].kip_content(kind) if len(self) == 1 else self

    def kip_summary(self) -> str:
        return "modules: " + ", ".join(m.name for m in self)


def _balanced(text: str, start: int, open_="(", close=")") -> int:
    """The index just past the bracket that closes the one at ``start``."""
    depth = 0
    for i in range(start, len(text)):
        if text[i] == open_:
            depth += 1
        elif text[i] == close:
            depth -= 1
            if depth == 0:
                return i + 1
    return len(text)


def _split(text: str, sep: str = ",") -> list[tuple[int, str]]:
    """Split at ``sep`` outside brackets; each piece with its offset."""
    out, depth, start = [], 0, 0
    for i, ch in enumerate(text):
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == sep and depth == 0:
            out.append((start, text[start:i]))
            start = i + 1
    out.append((start, text[start:]))
    return [(o, t) for o, t in out if t.strip()]


def _blank_comments(text: str, line: str, block: tuple[str, str] | None):
    """The text with comments blanked (offsets kept), and each line's comment."""
    comments: dict[int, str] = {}
    chars = list(text)
    i, n, lineno = 0, len(text), 1
    while i < n:
        if text[i] == "\n":
            lineno += 1
            i += 1
            continue
        if text[i] == '"':
            j = i + 1
            while j < n and text[j] != '"' and text[j] != "\n":
                j += 2 if text[j] == "\\" else 1
            i = j + 1
            continue
        if text.startswith(line, i):
            j = text.find("\n", i)
            j = n if j == -1 else j
            comments[lineno] = text[i + len(line):j].strip().lstrip("/!<- ").strip()
            for k in range(i, j):
                chars[k] = " "
            i = j
            continue
        if block and text.startswith(block[0], i):
            j = text.find(block[1], i + len(block[0]))
            j = n if j == -1 else j + len(block[1])
            inner = text[i + len(block[0]):j - len(block[1])]
            if "\n" not in inner and lineno not in comments:  # /* beside a port */ describes it
                comments[lineno] = inner.strip().strip("*").strip()
            for k in range(i, j):
                if chars[k] != "\n":
                    chars[k] = " "
            lineno += text.count("\n", i, j)
            i = j
            continue
        i += 1
    return "".join(chars), comments


def _comment_at(source: str, offset: int, comments: dict[int, str]) -> str:
    line = source.count("\n", 0, offset) + 1
    return comments.get(line, "")


_V_TYPES = {"wire", "reg", "logic", "bit", "byte", "int", "integer", "shortint", "longint", "signed", "unsigned",
            "tri", "wand", "wor", "var", "uwire", "time", "real", "string", "interconnect", "supply0", "supply1"}
_DIRECTIONS = {"input": "in", "output": "out", "inout": "inout", "ref": "inout"}


def _verilog_modules(text: str, path: Path | None) -> list[Module]:
    source, comments = _blank_comments(text, "//", ("/*", "*/"))
    source = re.sub(r"(?m)^\s*`.*$", lambda m: " " * len(m.group(0)), source)  # compiler directives
    modules = []
    for m in re.finditer(r"\b(module|macromodule|interface)\s+(?:automatic\s+|static\s+)?(\w+)", source):
        i = m.end()
        name = m.group(2)
        params: dict[str, str] = {}
        ports: list[Port] = []
        # the comment block just above the module describes it
        description = _comment_at(source, m.start() - 1, comments) if m.start() else ""
        while i < len(source) and source[i].isspace():
            i += 1
        if source.startswith("import", i):
            i = source.find(";", i) + 1
            while i < len(source) and source[i].isspace():
                i += 1
        if i < len(source) and source[i] == "#":
            j = source.find("(", i)
            end = _balanced(source, j)
            for _, item in _split(source[j + 1:end - 1]):
                pm = re.match(r"\s*(?:parameter\s+|localparam\s+)?(?:[\w:]+\s+)*?(?:\[[^\]]*\]\s*)?(\w+)\s*=\s*(.+)",
                              item, re.S)
                if pm and not item.strip().startswith("localparam"):
                    params[pm.group(1)] = " ".join(pm.group(2).split())
            i = end
            while i < len(source) and source[i].isspace():
                i += 1
        body_start = source.find(";", i)
        header_ports = ""
        header_offset = i
        if i < len(source) and source[i] == "(":
            end = _balanced(source, i)
            header_ports = source[i + 1:end - 1]
            header_offset = i + 1
            body_start = source.find(";", end)
        end_m = re.search(r"\bend(module|interface)\b", source[body_start:])
        body = source[body_start:body_start + end_m.start()] if end_m else source[body_start:]
        for pm in re.finditer(r"\b(?:parameter)\s+(?:[\w:]+\s+)*?(?:\[[^\]]*\]\s*)?(\w+)\s*=\s*([^;,]+)", body):
            params.setdefault(pm.group(1), " ".join(pm.group(2).split()))
        values = {}
        for k, v in params.items():
            values[k] = _evaluate(v, values)
        direction, kind, prange = None, "", ""
        ansi = bool(re.search(r"\b(input|output|inout|ref)\b", header_ports))
        if ansi:
            for offset, item in _split(header_ports):
                tokens = item.strip()
                dm = re.match(r"(input|output|inout|ref)\b\s*", tokens)
                if dm:
                    direction = _DIRECTIONS[dm.group(1)]
                    tokens = tokens[dm.end():]
                    kind, prange = "", ""
                    words = []
                    while True:
                        wm = re.match(r"(\w+(?:::\w+)?)\s*", tokens)
                        rm = re.match(r"(\[[^\]]*\])\s*", tokens)
                        if rm:
                            prange += rm.group(1)
                            tokens = tokens[rm.end():]
                            continue
                        if wm and (wm.group(1) in _V_TYPES or re.match(r"\w+::\w+|\w+_t$", wm.group(1))) \
                                and re.match(r"\w+(?:::\w+)?\s*[\w\[]", tokens):
                            words.append(wm.group(1))
                            tokens = tokens[wm.end():]
                            continue
                        break
                    kind = " ".join(words)
                elif re.match(r"\w+\.\w+\s+\w+", tokens):  # an interface port
                    im = re.match(r"(\w+\.\w+)\s+(\w+)", tokens)
                    ports.append(Port(im.group(2), "inout", im.group(1), None, "", ""))
                    continue
                nm = re.match(r"(\w+)", tokens)
                if not nm or direction is None:
                    continue
                pos = header_offset + offset + item.find(nm.group(1))
                ports.append(_vport(nm.group(1), direction, kind, prange, values,
                                    _comment_at(source, pos, comments)))
        else:
            order = [n.strip() for _, n in _split(header_ports) if n.strip()]
            declared: dict[str, Port] = {}
            for dm in re.finditer(r"\b(input|output|inout)\b\s*((?:\w+\s+)*?)(\[[^\]]*\])?\s*([\w\s,]+?)\s*;", body):
                kind = " ".join(w for w in dm.group(2).split() if w in _V_TYPES)
                for name in [n.strip() for n in dm.group(4).split(",") if n.strip()]:
                    pos = body_start + dm.start(4) + dm.group(4).find(name)
                    declared[name] = _vport(name, _DIRECTIONS[dm.group(1)], kind, dm.group(3) or "", values,
                                            _comment_at(source, pos, comments))
            ports = [declared[n] for n in order if n in declared] or list(declared.values())
        modules.append(Module(name, ports, params, "verilog", description, path))
    return modules


def _vport(name, direction, kind, prange, values, description) -> Port:
    width = 1
    if prange:
        width = 1
        for dim in re.findall(r"\[([^\]]*)\]", prange):
            if ":" in dim:
                msb, lsb = (_evaluate(p, values) for p in dim.split(":", 1))
                width = width * (abs(msb - lsb) + 1) if msb is not None and lsb is not None and width else None
            else:
                size = _evaluate(dim, values)
                width = width * size if size is not None and width else None
    elif kind in ("int", "integer"):
        width = 32
    elif kind == "byte":
        width = 8
    return Port(name, direction, kind, width, prange, description)


def _vhdl_modules(text: str, path: Path | None) -> list[Module]:
    source, comments = _blank_comments(text, "--", ("/*", "*/"))
    modules = []
    for m in re.finditer(r"(?i)\bentity\s+(\w+)\s+is\b", source):
        name = m.group(1)
        end_m = re.search(rf"(?i)\bend\b(\s+entity)?(\s+{name})?\s*;", source[m.end():])
        block_end = m.end() + (end_m.start() if end_m else len(source) - m.end())
        block = source[m.end():block_end]
        params: dict[str, str] = {}
        values: dict = {}
        gm = re.search(r"(?i)\bgeneric\s*\(", block)
        if gm:
            j = m.end() + gm.end() - 1
            end = _balanced(source, j)
            for _, item in _split(source[j + 1:end - 1], ";"):
                im = re.match(r"\s*([\w\s,]+?)\s*:\s*([^:=]+?)\s*(?::=\s*(.+))?\s*$", item, re.S)
                if im:
                    for g in im.group(1).split(","):
                        params[g.strip()] = " ".join((im.group(3) or "").split())
                        values[g.strip().lower()] = _evaluate(params[g.strip()], values)
        ports = []
        pm = re.search(r"(?i)\bport\s*\(", block)
        if pm:
            j = m.end() + pm.end() - 1
            end = _balanced(source, j)
            for offset, item in _split(source[j + 1:end - 1], ";"):
                im = re.match(r"\s*([\w\s,]+?)\s*:\s*(in|out|inout|buffer|linkage)\s+(.+?)\s*(?::=.*)?$",
                              item, re.S | re.I)
                if not im:
                    continue
                direction = {"in": "in", "out": "out", "buffer": "out"}.get(im.group(2).lower(), "inout")
                kind = " ".join(im.group(3).split())
                width = 1
                rm = re.search(r"\(\s*(.+?)\s+(downto|to)\s+(.+?)\s*\)", kind, re.I)
                prange = ""
                if rm:
                    prange = rm.group(0)
                    hi, lo = _evaluate(rm.group(1), values), _evaluate(rm.group(3), values)
                    width = abs(hi - lo) + 1 if hi is not None and lo is not None else None
                elif re.match(r"(?i)(integer|natural|positive)\b", kind):
                    span = re.search(r"(?i)range\s+(.+?)\s+to\s+(.+)$", kind)
                    top = _evaluate(span.group(2), values) if span else None
                    low = _evaluate(span.group(1), values) if span else None
                    width = (_clog2(top + 1) if low is not None and low >= 0 else _clog2(top + 1) + 1) \
                        if top is not None else 32
                type_name = re.sub(r"\s*\(.*", "", kind)
                for n in im.group(1).split(","):
                    pos = j + 1 + offset + item.find(n.strip())
                    ports.append(Port(n.strip(), direction, type_name, width, prange,
                                      _comment_at(source, pos, comments)))
        modules.append(Module(name, ports, params, "vhdl", "", path))
    return modules


def read_hdl(path) -> Modules:
    """The modules (or entities) of a Verilog, SystemVerilog or VHDL file.

    ``read_hdl("rtl/uart_tx.v")["uart_tx"]``; with one module, a draw cell
    shows it as a block and a table cell lists its ports.
    """
    from .authoring import project_path
    path = project_path(path)
    text = path.read_text(encoding="utf-8", errors="replace")
    vhdl = path.suffix.lower() in (".vhd", ".vhdl") or re.search(r"(?i)\bentity\s+\w+\s+is\b", text)
    modules = _vhdl_modules(text, path) if vhdl else _verilog_modules(text, path)
    if not modules:
        raise ValueError(f"{path.name}: no module or entity found")
    return Modules(modules)

# -- waveforms ------------------------------------------------------------------------

_SCALE = {"s": 1.0, "ms": 1e-3, "us": 1e-6, "ns": 1e-9, "ps": 1e-12, "fs": 1e-15}


class Wave:
    """One signal of a value-change dump: its changes over time.

    Times are in the dump's units, read as quantities with :meth:`edges`,
    :meth:`period` and :meth:`frequency`.
    """

    def __init__(self, name: str, width: int, changes: list, trace: "Trace", kind: str = "wire"):
        self.name, self.width, self.changes, self.trace, self.kind = name, width, changes, trace, kind

    def __repr__(self) -> str:
        return f"<Wave {self.name} [{self.width}] {len(self.changes)} changes>"

    def kip_summary(self) -> str:
        bits = f"{self.width} bits" if self.width > 1 else "1 bit"
        return f"signal {self.name}: {bits}, {self.toggles} changes"

    @property
    def short(self) -> str:
        return self.name.rsplit(".", 1)[-1]

    def value_at(self, t) -> str:
        """The value at time ``t`` (a quantity, or dump units): ``"1"``, ``"x"``, ``"1010"``."""
        ticks = self.trace._ticks(t)
        value = "x"
        for time, v in self.changes:
            if time > ticks:
                break
            value = v
        return value

    def int_at(self, t) -> int | None:
        value = self.value_at(t)
        return int(value, 2) if re.fullmatch(r"[01]+", value) else None

    def edges(self, kind: str = "rising") -> list:
        """Times of rising (0 to 1) or falling edges."""
        out, prev = [], None
        for time, v in self.changes:
            if prev is not None:
                if kind == "rising" and prev == "0" and v == "1" or kind == "falling" and prev == "1" and v == "0":
                    out.append(time)
            prev = v
        return [self.trace._time(t) for t in out]

    def pulses(self, level: str = "1") -> list:
        """How long each complete run at ``level`` lasts: ``tx.pulses("0")``."""
        out = []
        for (t0, v), (t1, _) in zip(self.changes, self.changes[1:]):
            if v == str(level) and t0 > 0:
                out.append(self.trace._time(t1 - t0))
        return out

    def pulse(self, level: str = "1", n: int = 1):
        """The ``n``-th complete pulse at ``level``: a UART start bit is ``tx.pulse("0")``."""
        found = self.pulses(level)
        if len(found) < n:
            raise ValueError(f"{self.name} has {len(found)} complete pulse{'s' if len(found) != 1 else ''} "
                             f"at {level}, not {n}")
        return found[n - 1]

    @property
    def toggles(self) -> int:
        return max(0, len(self.changes) - 1)

    def period(self):
        edges = [e.magnitude for e in self.edges("rising")]
        if len(edges) < 2:
            raise ValueError(f"{self.name} has fewer than two rising edges")
        return ureg.Quantity((edges[-1] - edges[0]) / (len(edges) - 1), self.trace.unit)

    def frequency(self):
        return (1 / self.period()).to("MHz")

    def duty(self) -> float:
        """The fraction of the dump spent high."""
        high, prev_t, prev_v = 0, None, None
        for time, v in self.changes + [(self.trace.end, None)]:
            if prev_v == "1":
                high += time - prev_t
            prev_t, prev_v = time, v
        span = self.trace.end - (self.changes[0][0] if self.changes else 0)
        return high / span if span else 0.0

    def segments(self, t0: int, t1: int):
        """(start, end, value) runs between t0 and t1 in dump units."""
        out, current, start = [], "x", t0
        for time, v in self.changes:
            if time <= t0:
                current = v
                continue
            if time >= t1:
                break
            if v != current:
                out.append((start, time, current))
                start, current = time, v
        out.append((start, t1, current))
        return out


class Trace:
    """A value-change dump: every signal, by its full or its short name.

    ``trace["clk"]`` is a :class:`Wave`; a draw cell shows a timing diagram
    (``trace.timing("clk", "tx", start=0 * ns, end=2 * us)`` picks signals).
    """

    def __init__(self, waves: dict[str, Wave], timescale: float, end: int, *, name: str = ""):
        self.waves, self.timescale, self.end, self.name = waves, timescale, end, name
        for w in waves.values():
            w.trace = self

    @property
    def unit(self) -> str:
        """The unit times are given in: the one that suits the dump's length (µs for 90 µs)."""
        span = max(self.end, 1) * self.timescale
        for unit, scale in (("s", 1.0), ("ms", 1e-3), ("us", 1e-6), ("ns", 1e-9), ("ps", 1e-12), ("fs", 1e-15)):
            if span >= scale * 0.999:
                return unit
        return "fs"

    def _time(self, ticks: int):
        q = ureg.Quantity(ticks * self.timescale, "s")
        return q.to(self.unit)

    def _ticks(self, t) -> int:
        if isinstance(t, ureg.Quantity):
            return round(t.to("s").magnitude / self.timescale)
        return int(t)

    @property
    def duration(self):
        return self._time(self.end)

    def __getitem__(self, name: str) -> Wave:
        if name in self.waves:
            return self.waves[name]
        matches = [w for full, w in self.waves.items() if full.endswith("." + name) or w.short == name]
        if len(matches) == 1:
            return matches[0]
        shortest = sorted(matches, key=lambda w: w.name.count("."))
        if shortest and (len(shortest) == 1 or shortest[0].name.count(".") < shortest[1].name.count(".")):
            return shortest[0]
        if not matches:
            raise KeyError(f"no signal {name!r}; there are {', '.join(sorted(w.short for w in self.waves.values())[:20])}")
        raise KeyError(f"{name!r} is ambiguous: {', '.join(w.name for w in matches)}")

    def __contains__(self, name) -> bool:
        try:
            self[name]
            return True
        except KeyError:
            return False

    @property
    def names(self) -> list[str]:
        return list(self.waves)

    def timing(self, *names: str, start=None, end=None, width: float = 170, caption: str | None = None,
               radix: str = "hex"):
        """The signals as a timing diagram, from ``start`` to ``end`` (quantities)."""
        chosen = [self[n] for n in names] if names else _default_signals(self)
        t0 = self._ticks(start) if start is not None else 0
        t1 = self._ticks(end) if end is not None else self.end
        if t1 <= t0:
            raise ValueError("timing() needs end after start")
        rows = []
        for w in chosen:
            segments = []
            for a, b, v in w.segments(t0, t1):
                if w.width == 1 and w.kind != "real":
                    segments.append((a, b, v if v in "01xz" else "x"))
                else:
                    segments.append((a, b, _radix(v, radix, w.kind)))
            rows.append(_Row(w.short, "bit" if w.width == 1 and w.kind != "real" else "bus", segments))
        return timing_diagram(rows, t0, t1, width=width, caption=caption,
                              axis=(self.timescale, self.unit))

    def kip_content(self, kind: str):
        return self.timing() if kind == "draw" else self

    def kip_summary(self) -> str:
        return (f"waveform {self.name}: {len(self.waves)} signals over {fmt_quantity(self.duration)}")


def _default_signals(trace: Trace) -> list[Wave]:
    """The top scope's signals (at most 16), clocks first."""
    waves = list(trace.waves.values())
    depth = min((w.name.count(".") for w in waves), default=0)
    top = [w for w in waves if w.name.count(".") == depth] or waves
    top.sort(key=lambda w: (not re.search(r"clk|clock", w.short, re.I), waves.index(w)))
    return top[:16]


def _radix(value: str, radix: str, kind: str) -> str:
    if kind == "real":
        try:
            return f"{float(value):g}"
        except ValueError:
            return value
    if not re.fullmatch(r"[01]+", value):
        if re.fullmatch(r"[xX]+", value):
            return "x"
        if re.fullmatch(r"[zZ]+", value):
            return "z"
        return value
    n = int(value, 2)
    if radix == "dec":
        return str(n)
    if radix == "bin":
        return value
    return f"{n:X}"


def read_vcd(path) -> Trace:
    """A value-change dump (``.vcd``) from a Verilog or VHDL simulator."""
    from .authoring import project_path
    path = project_path(path)
    text = path.read_text(encoding="utf-8", errors="replace")
    tokens = text.split()
    i, n = 0, len(tokens)
    scope: list[str] = []
    ids: dict[str, list[tuple[str, int, str]]] = {}
    timescale = 1e-9
    time = 0
    changes: dict[str, list] = {}
    end = 0
    while i < n:
        tok = tokens[i]
        if tok == "$timescale":
            j = tokens.index("$end", i)
            spec = "".join(tokens[i + 1:j])
            m = re.fullmatch(r"(\d+)\s*([munpf]?s)", spec)
            if m:
                timescale = int(m.group(1)) * _SCALE[m.group(2)]
            i = j + 1
        elif tok == "$scope":
            scope.append(tokens[i + 2])
            i = tokens.index("$end", i) + 1
        elif tok == "$upscope":
            if scope:
                scope.pop()
            i = tokens.index("$end", i) + 1
        elif tok == "$var":
            j = tokens.index("$end", i)
            kind, width, ident, ref = tokens[i + 1], int(tokens[i + 2]), tokens[i + 3], tokens[i + 4]
            full = ".".join(scope + [ref])
            ids.setdefault(ident, []).append((full, width, "real" if kind in ("real", "realtime") else "wire"))
            changes.setdefault(ident, [])
            i = j + 1
        elif tok in ("$comment", "$date", "$version"):
            i = tokens.index("$end", i) + 1
        elif tok in ("$enddefinitions", "$dumpvars", "$dumpall", "$dumpon", "$dumpoff", "$end"):
            i += 1 if tok != "$enddefinitions" else tokens.index("$end", i) + 1 - i
        elif tok.startswith("#"):
            time = int(tok[1:])
            end = max(end, time)
            i += 1
        elif tok[0] in "bBrR":
            value, ident = tok[1:], tokens[i + 1]
            if ident in changes:
                changes[ident].append((time, value.lower()))
            i += 2
        elif tok[0] in "01xXzZ":
            ident = tok[1:]
            if ident in changes:
                changes[ident].append((time, tok[0].lower()))
            i += 1
        else:
            i += 1
    waves: dict[str, Wave] = {}
    for ident, refs in ids.items():
        seq = []
        for t, v in changes.get(ident, []):
            if seq and seq[-1][0] == t:
                seq[-1] = (t, v)
            elif not seq or seq[-1][1] != v:
                seq.append((t, v))
        for full, width, kind in refs:
            if width > 1 and kind != "real":
                seq_w = [(t, v.rjust(width, "0" if v[0] == "1" or v[0] == "0" else v[0])) for t, v in seq]
            else:
                seq_w = seq
            waves[full] = Wave(full, width, seq_w, None, kind)  # type: ignore[arg-type]
    return Trace(waves, timescale, end, name=path.stem)

# -- timing diagrams ---------------------------------------------------------------------


@dataclass
class _Row:
    name: str
    kind: str                    # "bit", "bus", "clock", "label", "space"
    segments: list = field(default_factory=list)  # (t0, t1, value[, colour])
    gaps: list = field(default_factory=list)


#: WaveDrom's data colours, ``2`` to ``9``, lightened for paper.
_DATA = {"2": "#fdfbf4", "3": "#fff3b0", "4": "#ffd9a8", "5": "#c8e6ff", "6": "#c9f0d0", "7": "#e3d4f7",
         "8": "#d9eef0", "9": "#ffd0d6", "=": "#fdfbf4"}


def _nice_step(span: float, target: int = 8) -> float:
    raw = span / target
    mag = 10 ** math.floor(math.log10(raw)) if raw > 0 else 1
    return next(m * mag for m in (1, 2, 5, 10) if m * mag >= raw)


def timing_diagram(rows: list, t0: float, t1: float, *, width: float = 170, caption: str | None = None,
                   axis=None, title: str | None = None, cycles: int | None = None):
    """Draw timing rows; ``axis=(seconds per unit, unit)`` labels the time below."""
    canvas = Canvas()
    size = 2.3
    label_w = max((text_width(r.name, size) for r in rows if r.kind != "space"), default=0) + 3.0
    plot_w = max(30.0, width - label_w - 2.0)
    scale = plot_w / (t1 - t0)
    pitch, h = 6.0, 3.6
    y = 0.0
    if title:
        canvas.text(label_w + plot_w / 2, 3.0, title, size=size * 1.2, anchor="middle", font=SERIF, weight="bold")
        y = 6.0
    top = y
    if cycles:
        for k in range(cycles + 1):
            x = label_w + k * plot_w / cycles
            canvas.line(x, top, x, top + pitch * len(rows), stroke="#e2d9c3", width=0.15)
    for row in rows:
        if row.kind == "space":
            y += pitch * 0.6
            continue
        if row.kind == "label":
            canvas.text(0, y + pitch / 2, row.name, size=size, middle=True, weight="bold", font=SERIF)
            y += pitch
            continue
        canvas.text(label_w - 2.0, y + pitch / 2, row.name, size=size, anchor="end", middle=True)
        hi, lo, mid = y + (pitch - h) / 2, y + (pitch + h) / 2, y + pitch / 2
        slope = 0.0 if row.kind == "clock" else min(0.5, 0.25 * scale * (t1 - t0) / max(1, len(row.segments)) / 10)
        slope = min(slope, 0.4)
        if row.kind in ("bit", "clock"):
            points = []
            for k, seg in enumerate(row.segments):
                a, b, v = seg[0], seg[1], seg[2]
                xa, xb = label_w + (a - t0) * scale, label_w + (b - t0) * scale
                if v in ("x",):
                    canvas.polyline([(xa + slope, hi), (xb, hi), (xb, lo), (xa + slope, lo)], closed=True,
                                    fill="#e8dcc8", stroke=None)
                    for hx in range(int((xb - xa) / 1.2) + 1):
                        x = xa + hx * 1.2
                        canvas.line(max(xa, x), lo, min(xb, x + h * 0.6), hi, stroke="#b9a988", width=0.15)
                level = {"1": hi, "0": lo, "z": mid}.get(v, mid if v == "x" else None)
                colour = "#2a4f9e" if v == "z" else INK
                if v == "x":
                    if points:
                        canvas.polyline(points, stroke=INK, width=0.3)
                    points = []
                    canvas.line(xa, hi, xb, hi, stroke=INK, width=0.3)
                    canvas.line(xa, lo, xb, lo, stroke=INK, width=0.3)
                    continue
                if v == "z":
                    if points:
                        canvas.polyline(points, stroke=INK, width=0.3)
                    points = []
                    canvas.line(xa, mid, xb, mid, stroke=colour, width=0.3)
                    continue
                if not points:
                    points = [(xa, level)]
                else:
                    points.append((xa + slope, level))
                points.append((xb, level))
            if points:
                canvas.polyline(points, stroke=INK, width=0.3)
        else:
            for seg in row.segments:
                a, b, v = seg[0], seg[1], seg[2]
                fill = seg[3] if len(seg) > 3 else "#fdfbf4"
                xa, xb = label_w + (a - t0) * scale, label_w + (b - t0) * scale
                s = min(slope + 0.5, (xb - xa) / 2)
                if v == "z":
                    canvas.line(xa, mid, xb, mid, stroke="#2a4f9e", width=0.3)
                    continue
                shape = [(xa, mid), (xa + s, hi), (xb - s, hi), (xb, mid), (xb - s, lo), (xa + s, lo)]
                if v == "x":
                    canvas.polyline(shape, closed=True, fill="#e8dcc8", stroke=INK, width=0.3)
                    continue
                canvas.polyline(shape, closed=True, fill=fill, stroke=INK, width=0.3)
                label = str(v)
                room = xb - xa - 2 * s - 0.6
                fs = size * 0.9
                if text_width(label, fs) > room:
                    while label and text_width(label + "…", fs) > room:
                        label = label[:-1]
                    label = label + "…" if label else ""
                if label:
                    canvas.text((xa + xb) / 2, mid, label, size=fs, anchor="middle", middle=True)
        for g in row.gaps:
            gx = label_w + (g - t0) * scale
            canvas.polyline([(gx - 0.6, lo + 0.6), (gx + 0.2, hi - 0.6), (gx + 1.0, hi - 0.6), (gx + 0.2, lo + 0.6)],
                            closed=True, fill="#f7f2e3", stroke=None)
            canvas.line(gx - 0.6, lo + 0.6, gx + 0.2, hi - 0.6, stroke=INK, width=0.25)
            canvas.line(gx + 0.2, lo + 0.6, gx + 1.0, hi - 0.6, stroke=INK, width=0.25)
        y += pitch
    if axis is not None:
        seconds, unit = axis
        span = (t1 - t0) * seconds
        q = ureg.Quantity(span, "s")
        from .spice import _engineering
        shown = _engineering(q)
        factor = shown.magnitude / (t1 - t0) if t1 > t0 else 1.0
        step = _nice_step(shown.magnitude)
        canvas.line(label_w, y + 0.5, label_w + plot_w, y + 0.5, stroke=FAINT, width=0.2)
        k = math.ceil(t0 * factor / step)
        while k * step <= t1 * factor + 1e-9:
            x = label_w + (k * step / factor - t0) * scale
            canvas.line(x, y + 0.5, x, y + 1.5, stroke=FAINT, width=0.2)
            canvas.text(x, y + 4.0, f"{k * step:g}", size=size * 0.8, anchor="middle", fill=FAINT)
            k += 1
        canvas.text(label_w + plot_w, y + 7.2, f"time ({shown.units:~P})".replace("µ", "µ"), size=size * 0.8,
                    anchor="end", fill=FAINT, font=SERIF)
    return canvas.drawing(width=width, caption=caption, margin=1.0)

# -- WaveDrom -------------------------------------------------------------------------


def _json5(text: str):
    """WaveDrom's relaxed JSON: unquoted keys, single quotes, trailing commas, comments."""
    text = re.sub(r"//[^\n]*", "", text)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    out, i, n = [], 0, len(text)
    while i < n:
        ch = text[i]
        if ch in "'\"":
            j = i + 1
            buf = []
            while j < n and text[j] != ch:
                if text[j] == "\\" and j + 1 < n:
                    buf.append(text[j:j + 2])
                    j += 2
                    continue
                buf.append('\\"' if text[j] == '"' else text[j])
                j += 1
            out.append('"' + "".join(buf) + '"')
            i = j + 1
            continue
        m = re.match(r"[A-Za-z_$][\w$]*", text[i:])
        if m and re.match(r"\s*:", text[i + m.end():]):
            out.append(f'"{m.group(0)}"')
            i += m.end()
            continue
        out.append(ch)
        i += 1
    cleaned = re.sub(r",\s*([}\]])", r"\1", "".join(out))
    return json.loads(cleaned)


def wavedrom(spec, *, width: float = 170, caption: str | None = None):
    """A WaveDrom timing diagram, from its JSON (a dict, the text, or a ``.json`` file).

    ``{signal: [{name: "clk", wave: "p......"}, {name: "data", wave: "x.345x.",
    data: ["a", "b", "c"]}]}``: clocks (``p n h l``), levels (``0 1``), unknown
    ``x``, high impedance ``z``, data (``= 2``–``9``, labelled from ``data``),
    ``.`` to hold and ``|`` for a gap; groups as ``["name", ...]``.
    """
    if isinstance(spec, (str, Path)):
        text = str(spec)
        if "\n" not in text and "{" not in text:
            from .authoring import project_path
            text = project_path(text).read_text(encoding="utf-8")
        spec = _json5(text)
    signals = spec.get("signal", [])
    config = spec.get("config", {}) or {}
    hscale = float(config.get("hscale", 1) or 1)
    rows: list[_Row] = []
    length = 0

    def walk(items, depth=0):
        nonlocal length
        for item in items:
            if isinstance(item, list):
                if item and isinstance(item[0], str):
                    rows.append(_Row(("  " * depth) + item[0], "label"))
                    walk(item[1:], depth + 1)
                else:
                    walk(item, depth)
                continue
            if not isinstance(item, dict) or "wave" not in item:
                rows.append(_Row("", "space"))
                continue
            row = _wave_row(item, ("  " * depth) + str(item.get("name", "")))
            length = max(length, row[1])
            rows.append(row[0])

    walk(signals)
    if not length:
        raise ValueError("this WaveDrom spec has no signal with a wave")
    head = spec.get("head", {}) or {}
    return timing_diagram(rows, 0.0, float(length), width=width * min(1.0, hscale), caption=caption,
                          title=head.get("text") if isinstance(head.get("text"), str) else None,
                          cycles=int(length))


def _wave_row(item: dict, name: str) -> tuple[_Row, float]:
    wave = str(item["wave"])
    period = float(item.get("period", 1) or 1)
    phase = float(item.get("phase", 0) or 0)
    data = item.get("data", [])
    if isinstance(data, str):
        data = data.split()
    data = list(data)
    clocky = all(c in "pnPNhlHL.|" for c in wave)
    segments: list = []
    gaps: list = []
    previous = None
    t = -phase
    di = 0
    for ch in wave:
        a, b = t, t + period
        if ch == "|":
            gaps.append(a + period / 2)
            ch = "."
        if ch == ".":
            ch = previous or "x"
            if ch in "=23456789":  # held data: extend the last segment
                if segments:
                    last = segments[-1]
                    segments[-1] = (last[0], b, *last[2:])
                t = b
                continue
        else:
            previous = ch
        if ch in "pP":
            segments += [(a, a + period / 2, "1"), (a + period / 2, b, "0")]
        elif ch in "nN":
            segments += [(a, a + period / 2, "0"), (a + period / 2, b, "1")]
        elif ch in "hH1u":
            segments.append((a, b, "1"))
        elif ch in "lL0d":
            segments.append((a, b, "0"))
        elif ch in "xX":
            segments.append((a, b, "x"))
        elif ch == "z":
            segments.append((a, b, "z"))
        elif ch in "=23456789":
            label = str(data[di]) if di < len(data) else ""
            di += 1
            segments.append((a, b, label, _DATA.get(ch, "#fdfbf4")))
        t = b
    merged: list = []
    for seg in segments:
        if merged and merged[-1][2] == seg[2] and len(seg) == 3 and len(merged[-1]) == 3:
            merged[-1] = (merged[-1][0], seg[1], seg[2])
        else:
            merged.append(seg)
    merged = [(max(0.0, s[0]), *s[1:]) for s in merged if s[1] > 0]
    bus = any(len(s) > 3 for s in merged)
    kind = "bus" if bus else ("clock" if clocky else "bit")
    return _Row(name, kind, merged, gaps), t

# -- FPGA reports ------------------------------------------------------------------------


class Utilization:
    """Resource use after synthesis or place-and-route: ``(resource, used, available)``.

    ``util["LUT"]`` is the first resource whose name contains LUT; ``util.percent("LUT")``
    its use as a percentage. A table cell shows every resource, the over-full in red.
    """

    def __init__(self, rows: list[tuple[str, float, float | None]], *, tool: str = "", name: str = ""):
        self.rows, self.tool, self.name = rows, tool, name

    def _find(self, key: str):
        low = key.lower()
        exact = [r for r in self.rows if r[0].lower() == low]
        if exact:
            return exact[0]
        partial = [r for r in self.rows if low in r[0].lower()]
        if partial:
            return partial[0]
        raise KeyError(f"no resource {key!r}; there are {', '.join(r[0] for r in self.rows)}")

    def __getitem__(self, key: str) -> float:
        return self._find(key)[1]

    def available(self, key: str):
        return self._find(key)[2]

    def percent(self, key: str):
        _, used, avail = self._find(key)
        if not avail:
            raise ValueError(f"{key}: the report gives no total available")
        return ureg.Quantity(100 * used / avail, "percent")

    def table(self, *resources: str, limit: float = 80.0, titles: dict | None = None, **options):
        """The resources in use (or those named), with their use; any above ``limit``
        percent is marked. ``titles`` renames them: ``{"ICESTORM_LC": "Logic cells"}``."""
        from .content import Column, Table
        titles = titles or {}
        chosen = [self._find(r) for r in resources] if resources else [r for r in self.rows if r[1]]
        rows, marks = [], {}
        for k, (resource, used, avail) in enumerate(chosen):
            resource = titles.get(resource, resource)
            pct = 100 * used / avail if avail else None
            rows.append((resource, _int(used), _int(avail) if avail else "–", f"{pct:.1f}" if pct is not None else "–"))
            if pct is not None and pct > limit:
                marks[k] = "fail"
        columns = [Column("resource", "Resource"), Column("used", "Used", align="right"),
                   Column("available", "Available", align="right"), Column("pct", "Use (%)", align="right")]
        if not any(r[2] for r in chosen):  # synthesis counts cells without a device to fill
            columns, rows = columns[:2], [r[:2] for r in rows]
        return Table(columns, rows, highlight=marks, **options)

    def kip_content(self, kind: str):
        return self.table() if kind == "table" else self

    def kip_summary(self) -> str:
        return f"{self.tool} utilization: " + ", ".join(f"{r[0]} {_int(r[1])}" for r in self.rows[:6])


def _int(v):
    return int(v) if isinstance(v, float) and v.is_integer() else v


def _number(text: str) -> float | None:
    text = text.strip().replace(",", "")
    try:
        return float(text)
    except ValueError:
        return None


def read_utilization(path) -> Utilization:
    """A utilization report: Vivado ``report_utilization``, Quartus fit summary,
    Yosys ``stat`` (text or ``-json``), or nextpnr's ``--report`` JSON."""
    from .authoring import project_path
    path = project_path(path)
    text = path.read_text(encoding="utf-8", errors="replace")
    stripped = text.lstrip()
    if stripped.startswith("{"):
        data = json.loads(text)
        if "utilization" in data:  # nextpnr
            rows = [(k, float(v.get("used", 0)), float(v.get("available", 0)) or None)
                    for k, v in data["utilization"].items()]
            rows = [r for r in rows if r[1] or r[2]]
            return Utilization(rows, tool="nextpnr", name=path.stem)
        design = data.get("design") or {}
        cells = design.get("num_cells_by_type") or {}
        if not cells and "modules" in data:
            for module in data["modules"].values():
                cells = module.get("num_cells_by_type") or cells
        rows = [(k, float(v), None) for k, v in sorted(cells.items(), key=lambda kv: -kv[1])]
        return Utilization(rows, tool="yosys", name=path.stem)
    if "| Site Type" in text or "Utilization Design Information" in text:
        rows, seen = [], set()
        for line in text.splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) < 5 or line.lstrip().startswith("+") or cells[0] in ("Site Type", "Ref Name"):
                continue
            raw = line.strip().strip("|").split("|")[0]
            if raw.startswith("   "):  # an indented breakdown row
                continue
            used, avail = _number(cells[1]), _number(cells[-2])
            if used is None or avail is None or cells[0] in seen:
                continue
            seen.add(cells[0])
            rows.append((cells[0], used, avail or None))
        return Utilization(rows, tool="vivado", name=path.stem)
    rows = []
    for m in re.finditer(r"(?m)^\s*([A-Za-z][\w /()\-]*?)\s*:\s*([\d,]+)\s*/\s*([\d,]+)", text):  # Quartus
        rows.append((m.group(1).strip(), _number(m.group(2)), _number(m.group(3))))
    if rows:
        return Utilization(rows, tool="quartus", name=path.stem)
    # yosys stat: "     SB_LUT4   30" before 0.40, "       30   SB_LUT4" since; the last
    # module's table (the top after hierarchy) is the one to read
    blocks = re.split(r"(?m)^=== ", text)
    body = blocks[-1] if len(blocks) > 1 else text
    for m in re.finditer(r"(?m)^\s+(\$?[A-Za-z_][\w$]*)\s+(\d+)\s*$", body):
        rows.append((m.group(1), float(m.group(2)), None))
    for m in re.finditer(r"(?m)^\s+(\d+)\s+(\$?[A-Za-z_][\w$]*)\s*$", body):
        if m.group(2) not in ("wires", "cells", "ports", "memories", "processes", "submodules"):
            rows.append((m.group(2), float(m.group(1)), None))
    total = re.search(r"Number of cells:\s*(\d+)", body) or re.search(r"(?m)^\s+(\d+)\s+cells\s*$", body)
    if total:
        rows.insert(0, ("cells", float(total.group(1)), None))
    if not rows:
        raise ValueError(f"{path.name}: not a utilization report kip recognises")
    seen, unique = set(), []
    for r in rows:
        if r[0] not in seen:
            seen.add(r[0])
            unique.append(r)
    return Utilization(unique, tool="yosys", name=path.stem)


class TimingReport:
    """Timing closure: worst slacks and each clock's period and achieved frequency.

    ``timing.wns`` (worst negative setup slack), ``timing.whs`` (hold),
    ``timing.met``, and ``timing.fmax("clk")``.
    """

    def __init__(self, *, wns=None, tns=None, whs=None, ths=None, clocks=None, tool="", name=""):
        self.wns, self.tns, self.whs, self.ths = wns, tns, whs, ths
        #: name -> {"period": ns, "target": MHz, "achieved": MHz}
        self.clocks: dict[str, dict] = clocks or {}
        self.tool, self.name = tool, name

    @property
    def met(self) -> bool:
        slacks = [s for s in (self.wns, self.whs) if s is not None]
        if slacks:
            return all(s.magnitude >= 0 for s in slacks)
        achieved = [(c.get("achieved"), c.get("target")) for c in self.clocks.values()]
        return all(a is not None and t is not None and a >= t for a, t in achieved) if achieved else False

    def fmax(self, clock: str | None = None):
        """The achieved maximum frequency of ``clock`` (the only, or slowest, by default)."""
        known = {k: v for k, v in self.clocks.items() if v.get("achieved") is not None}
        if not known and self.wns is not None and self.clocks:
            for k, v in self.clocks.items():
                if v.get("period") is not None:
                    known[k] = {"achieved": 1000 / (v["period"] - self.wns.magnitude)}
        if not known:
            raise ValueError("this report gives no achieved frequency")
        if clock is None:
            value = min(v["achieved"] for v in known.values())
        else:
            match = [v for k, v in known.items() if k == clock or clock in k]
            if not match:
                raise KeyError(f"no clock {clock!r}; there are {', '.join(known)}")
            value = match[0]["achieved"]
        return ureg.Quantity(value, "MHz")

    def table(self, **options):
        from .content import Column, Table
        rows, marks = [], {}
        for label, value in (("Worst setup slack (WNS)", self.wns), ("Total setup slack (TNS)", self.tns),
                             ("Worst hold slack (WHS)", self.whs), ("Total hold slack (THS)", self.ths)):
            if value is not None:
                if value.magnitude < 0:
                    marks[len(rows)] = "fail"
                rows.append((label, f"{value.magnitude:g} ns"))
        for name, c in self.clocks.items():
            parts = []
            if c.get("period") is not None:
                parts.append(f"period {c['period']:g} ns")
            if c.get("target") is not None:
                parts.append(f"target {c['target']:g} MHz")
            if c.get("achieved") is not None:
                parts.append(f"achieved {c['achieved']:.2f} MHz")
                if c.get("target") is not None and c["achieved"] < c["target"]:
                    marks[len(rows)] = "fail"
            rows.append((f"Clock {name}", ", ".join(parts)))
        return Table([Column("item", "Item"), Column("value", "Value")], rows, highlight=marks, **options)

    def kip_content(self, kind: str):
        return self.table() if kind == "table" else self

    def kip_summary(self) -> str:
        bits = [f"WNS {self.wns.magnitude:g} ns" if self.wns is not None else ""]
        bits += [f"{k} {v['achieved']:.1f} MHz" for k, v in self.clocks.items() if v.get("achieved")]
        return f"{self.tool} timing ({'met' if self.met else 'NOT met'}): " + ", ".join(b for b in bits if b)


def _clock(name: str) -> str:
    """A clock as the design names it: nextpnr appends where it was buffered."""
    return re.sub(r"\$(SB_IO_IN|TRELLIS_IO_IN|glb_clk|IBUF|BUFG).*$", "", name) or name


def read_timing(path) -> TimingReport:
    """A timing report: Vivado ``report_timing_summary``, nextpnr's log or ``--report``
    JSON, OpenSTA/OpenROAD ``report_wns``/``report_tns``, or a Quartus STA summary."""
    from .authoring import project_path
    path = project_path(path)
    text = path.read_text(encoding="utf-8", errors="replace")
    ns = lambda v: ureg.Quantity(float(v), "ns") if v is not None else None  # noqa: E731
    if text.lstrip().startswith("{"):
        data = json.loads(text)
        clocks = {_clock(k): {"achieved": float(v.get("achieved")) if v.get("achieved") is not None else None,
                      "target": float(v.get("constraint")) if v.get("constraint") is not None else None}
                  for k, v in (data.get("fmax") or {}).items()}
        return TimingReport(clocks=clocks, tool="nextpnr", name=path.stem)
    m = re.search(r"WNS\(ns\)\s+TNS\(ns\).*?\n\s*-+.*?\n\s*([-\d.]+)\s+([-\d.]+)\s+\d+\s+\d+\s+([-\d.]+)\s+([-\d.]+)",
                  text, re.S)
    if m:  # Vivado
        clocks = {}
        cs = re.search(r"Clock Summary.*?\n-+\n(.*?)\n\n", text, re.S)
        if cs:
            for line in cs.group(1).splitlines():
                cm = re.match(r"\s*(\S+)\s+\{[^}]*\}\s+([\d.]+)\s+([\d.]+)", line)
                if cm:
                    clocks[cm.group(1)] = {"period": float(cm.group(2)), "target": float(cm.group(3))}
        report = TimingReport(wns=ns(m.group(1)), tns=ns(m.group(2)), whs=ns(m.group(3)), ths=ns(m.group(4)),
                              clocks=clocks, tool="vivado", name=path.stem)
        for k, c in report.clocks.items():
            c["achieved"] = 1000 / (c["period"] - report.wns.magnitude) if c.get("period") else None
        return report
    found = re.findall(r"Max frequency for clock\s+'([^']+)':\s*([\d.]+)\s*MHz\s*\((PASS|FAIL) at ([\d.]+) MHz\)", text)
    if found:  # nextpnr log: the last report is after routing
        clocks = {}
        for name, achieved, _, target in found:
            clocks[_clock(name)] = {"achieved": float(achieved), "target": float(target)}
        return TimingReport(clocks=clocks, tool="nextpnr", name=path.stem)
    wns = re.search(r"(?im)^\s*(?:wns|worst slack)\s*:?\s*([-\d.]+)", text)
    tns = re.search(r"(?im)^\s*tns\s*:?\s*([-\d.]+)", text)
    if wns or tns:  # OpenSTA / OpenROAD
        clocks = {}
        for cm in re.finditer(r"(?im)^\s*(\S+)\s+period_min\s*=\s*([\d.]+)\s+fmax\s*=\s*([\d.]+)", text):
            clocks[cm.group(1)] = {"period": float(cm.group(2)), "achieved": float(cm.group(3))}
        return TimingReport(wns=ns(wns.group(1)) if wns else None, tns=ns(tns.group(1)) if tns else None,
                            clocks=clocks, tool="opensta", name=path.stem)
    slack = re.findall(r"(?i)Type\s*:\s*(Setup|Hold)\s*'([^']+)'\s*\n\s*Slack\s*:\s*([-\d.]+)\s*\n\s*TNS\s*:\s*([-\d.]+)", text)
    if slack:  # Quartus
        setup = [(float(s), float(t)) for kind, _, s, t in slack if kind.lower() == "setup"]
        hold = [(float(s), float(t)) for kind, _, s, t in slack if kind.lower() == "hold"]
        return TimingReport(wns=ns(min(s for s, _ in setup)) if setup else None,
                            tns=ns(sum(t for _, t in setup)) if setup else None,
                            whs=ns(min(s for s, _ in hold)) if hold else None,
                            ths=ns(sum(t for _, t in hold)) if hold else None, tool="quartus", name=path.stem)
    raise ValueError(f"{path.name}: not a timing report kip recognises")

# -- constraints ----------------------------------------------------------------------


class Constraints:
    """Pin and clock constraints: ``pins`` (port, pin, I/O standard...) and ``clocks``."""

    def __init__(self, pins: list[dict], clocks: list[dict], *, tool: str = "", name: str = ""):
        self.pins, self.clocks, self.tool, self.name = pins, clocks, tool, name

    def pin(self, port: str) -> str:
        for p in self.pins:
            if p["port"] == port:
                return p.get("pin", "")
        raise KeyError(f"no constraint for port {port!r}")

    def table(self, **options):
        """The pin-out: each port's package pin and I/O standard."""
        from .content import Column, Table
        rows = [(p["port"], p.get("pin", ""), p.get("standard", ""), p.get("extra", "")) for p in
                sorted(self.pins, key=lambda p: _natural(p["port"]))]
        columns = [Column("port", "Port"), Column("pin", "Pin"), Column("std", "I/O standard"),
                   Column("extra", "Other")]
        keep = [k for k in range(4) if k < 2 or any(r[k] for r in rows)]
        return Table([columns[k] for k in keep], [tuple(r[k] for k in keep) for r in rows], **options)

    def clock_table(self, **options):
        from .content import Column, Table
        rows = [(c["name"], c.get("port", ""), f"{c['period']:g}", f"{1000 / c['period']:.4g}") for c in self.clocks]
        return Table([Column("name", "Clock"), Column("port", "Port"), Column("period", "Period (ns)", align="right"),
                      Column("f", "Frequency (MHz)", align="right")], rows, **options)

    def kip_content(self, kind: str):
        return self.table() if kind == "table" else self

    def kip_summary(self) -> str:
        return f"{self.tool} constraints: {len(self.pins)} pins, {len(self.clocks)} clocks"


def _natural(name: str):
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", name)]


def _ports(text: str) -> list[str]:
    """``[get_ports {a b[0]}]`` or ``[get_ports clk]`` as port names."""
    m = re.search(r"get_ports\s+(\{[^}]*\}|\"[^\"]*\"|\S+?)\s*\]", text)
    if not m:
        return []
    return m.group(1).strip("{}\"").split()


def read_constraints(path) -> Constraints:
    """Pin and clock constraints: Vivado ``.xdc``, Quartus ``.qsf``, Lattice ``.lpf``
    and ``.pcf`` (nextpnr/icestorm), Gowin ``.cst``, and ``.sdc`` clocks."""
    from .authoring import project_path
    path = project_path(path)
    text = path.read_text(encoding="utf-8", errors="replace")
    pins: dict[str, dict] = {}
    clocks: list[dict] = []
    suffix = path.suffix.lower()

    def pin(port):
        return pins.setdefault(port, {"port": port})

    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip() if suffix in (".xdc", ".sdc", ".pcf", ".qsf", ".tcl") else raw.strip()
        if suffix == ".lpf" or suffix == ".cst":
            line = re.sub(r"//.*", "", line).strip()
        if not line:
            continue
        m = re.match(r"set_property\s+-dict\s+\{([^}]*)\}\s*(\[.*\])", line)
        if m:
            props = dict(re.findall(r"(\S+)\s+(\S+)", m.group(1)))
            for port in _ports(m.group(2)):
                p = pin(port)
                if "PACKAGE_PIN" in props:
                    p["pin"] = props.pop("PACKAGE_PIN")
                if "IOSTANDARD" in props:
                    p["standard"] = props.pop("IOSTANDARD")
                if props:
                    p["extra"] = " ".join(f"{k}={v}" for k, v in props.items())
            continue
        m = re.match(r"set_property\s+(PACKAGE_PIN|IOSTANDARD|LOC)\s+(\S+)\s*(\[.*\])", line)
        if m:
            for port in _ports(m.group(3)):
                pin(port)["pin" if m.group(1) in ("PACKAGE_PIN", "LOC") else "standard"] = m.group(2)
            continue
        m = re.match(r"create_clock\s+(.*)", line)
        if m:
            period = re.search(r"-period\s+([\d.]+)", line)
            name = re.search(r"-name\s+(\S+)", line)
            ports = _ports(line)
            if period:
                clocks.append({"name": name.group(1) if name else (ports[0] if ports else "clock"),
                               "port": ports[0] if ports else "", "period": float(period.group(1))})
            continue
        m = re.match(r"set_io\s+(?:-\w+\s+)*(\S+)\s+(\S+)", line)  # pcf
        if m:
            pin(m.group(1))["pin"] = m.group(2)
            continue
        m = re.match(r'(?i)LOCATE\s+COMP\s+"([^"]+)"\s+SITE\s+"([^"]+)"', line)  # lpf
        if m:
            pin(m.group(1))["pin"] = m.group(2)
            continue
        m = re.match(r'(?i)IOBUF\s+PORT\s+"([^"]+)"\s+(.*?);?$', line)
        if m:
            props = dict(re.findall(r"(\w+)\s*=\s*(\S+?)(?:\s|;|$)", m.group(2)))
            p = pin(m.group(1))
            if "IO_TYPE" in props:
                p["standard"] = props.pop("IO_TYPE")
            if props:
                p["extra"] = " ".join(f"{k}={v}" for k, v in props.items())
            continue
        m = re.match(r'(?i)FREQUENCY\s+PORT\s+"([^"]+)"\s+([\d.]+)\s*MHZ', line)
        if m:
            clocks.append({"name": m.group(1), "port": m.group(1), "period": 1000 / float(m.group(2))})
            continue
        m = re.match(r"set_location_assignment\s+(?:PIN_)?(\S+)\s+-to\s+(\S+)", line)  # qsf
        if m:
            pin(m.group(2).strip('"'))["pin"] = m.group(1).replace("PIN_", "")
            continue
        m = re.match(r'set_instance_assignment\s+-name\s+IO_STANDARD\s+"?([^"]+?)"?\s+-to\s+(\S+)', line)
        if m:
            pin(m.group(2).strip('"'))["standard"] = m.group(1)
            continue
        m = re.match(r'(?i)IO_LOC\s+"([^"]+)"\s+([\w,]+)\s*;', line)  # Gowin cst
        if m:
            pin(m.group(1))["pin"] = m.group(2)
            continue
        m = re.match(r'(?i)IO_PORT\s+"([^"]+)"\s+(.*?);', line)
        if m:
            props = dict(re.findall(r"(\w+)\s*=\s*(\S+)", m.group(2)))
            p = pin(m.group(1))
            if "IO_TYPE" in props:
                p["standard"] = props.pop("IO_TYPE")
            if props:
                p["extra"] = " ".join(f"{k}={v}" for k, v in props.items())
    tool = {".xdc": "vivado", ".qsf": "quartus", ".lpf": "lattice", ".pcf": "nextpnr", ".cst": "gowin",
            ".sdc": "sdc"}.get(suffix, "")
    return Constraints([p for p in pins.values() if len(p) > 1 or p.get("pin")], clocks, tool=tool, name=path.stem)
