"""SPICE: netlists, simulation, and the waveforms simulators write.

- :func:`read_netlist` reads a SPICE netlist -- from ngspice, Xyce, LTspice,
  or exported by KiCad or xschem -- into a :class:`Netlist` of elements,
  models, subcircuits and analyses; :meth:`Netlist.with_values` puts a
  calculation's component values into it.
- :func:`simulate` runs it with ngspice and returns the :class:`Results`;
  with ``cache=`` the results are kept beside the document, so the document
  builds on a machine without ngspice for as long as the netlist is unchanged.
- :func:`read_raw` reads a raw file (ngspice or LTspice, binary or ASCII) or
  LTspice's exported text.

A vector is a :class:`Signal` with units, so measurements are quantities a
calc cell checks like any other::

    # %% calc response "Simulated response"
    H = ac.v("out") / ac.v("in")
    f_c = H.cutoff()                       # -> kHz
    assert abs(f_c - f_target) <= 0.05 * f_target, "Cut-off within 5 %"

``plot(H)`` draws a Bode magnitude plot; ``plot(tran.v("out"))`` a waveform.
"""
from __future__ import annotations

import hashlib
import math
import os
import re
import shutil
import struct
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .units import fmt_quantity, ureg

__all__ = ["spice_value", "Element", "Netlist", "read_netlist", "simulate", "read_raw",
           "Results", "Analysis", "Signal", "standard_value", "E_SERIES"]

# -- values ---------------------------------------------------------------------------

_SCALE = {"t": 1e12, "g": 1e9, "meg": 1e6, "k": 1e3, "mil": 25.4e-6, "m": 1e-3, "u": 1e-6,
          "µ": 1e-6, "μ": 1e-6, "n": 1e-9, "p": 1e-12, "f": 1e-15, "a": 1e-18}
_VALUE = re.compile(r"^([+-]?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?)(meg|mil|[tgkmuµμnpfa])?([a-zµμΩ]*)$",
                    re.I)
_RKM = re.compile(r"^(\d+)([kmuµnpgtr])(\d+)([a-zΩ]*)$", re.I)


def spice_value(text) -> float:
    """A SPICE number: ``4.7k`` is 4700, ``10Meg`` ten million, ``1m`` a thousandth.

    As in SPICE, ``M`` is milli and ``Meg`` mega, ``F`` is femto, and letters
    after the scale factor (``10uF``, ``1kOhm``) are ignored. ``4k7`` reads 4.7k.
    """
    if isinstance(text, (int, float)):
        return float(text)
    raw = str(text).strip().strip("{}'\"")
    m = _VALUE.match(raw)
    if m:
        scale = _SCALE[m.group(2).lower()] if m.group(2) else 1.0
        return float(m.group(1)) * scale
    m = _RKM.match(raw)
    if m:
        scale = 1.0 if m.group(2).lower() == "r" else _SCALE[m.group(2).lower()]
        return float(f"{m.group(1)}.{m.group(3)}") * scale
    raise ValueError(f"not a SPICE number: {text!r}")


def _try_value(text):
    try:
        return spice_value(text)
    except ValueError:
        return None


#: Each element letter: what it is, and the unit of its value.
_KINDS = {
    "R": ("resistor", "ohm"), "C": ("capacitor", "farad"), "L": ("inductor", "henry"),
    "K": ("coupling", None), "V": ("voltage source", "volt"), "I": ("current source", "ampere"),
    "D": ("diode", None), "Q": ("BJT", None), "J": ("JFET", None), "M": ("MOSFET", None),
    "Z": ("MESFET", None), "X": ("subcircuit", None), "E": ("VCVS", None), "G": ("VCCS", None),
    "F": ("CCCS", None), "H": ("CCVS", None), "B": ("behavioural source", None),
    "S": ("switch", None), "W": ("current switch", None), "T": ("transmission line", None),
    "O": ("lossy line", None), "U": ("RC line", None), "A": ("XSPICE model", None),
    "N": ("Verilog-A model", None), "P": ("coupled lines", None), "Y": ("transmission line", None),
}
#: Nodes an element joins, for the letters with a fixed count.
_NODES = {"R": 2, "C": 2, "L": 2, "V": 2, "I": 2, "D": 2, "J": 3, "Z": 3, "M": 4, "E": 4, "G": 4,
          "F": 2, "H": 2, "B": 2, "S": 4, "W": 2, "T": 4, "O": 4, "U": 3}

# -- netlists ---------------------------------------------------------------------------


@dataclass
class Element:
    """One netlist element: ``R1 in out 1k``."""

    name: str
    kind: str
    nodes: list[str]
    value: float | None = None
    model: str | None = None
    params: dict[str, str] = field(default_factory=dict)
    text: str = ""
    #: The value as written (``4.7k``, ``{Rf}``, ``DC 0 AC 1 SIN(0 1 1k)``).
    value_text: str = ""

    @property
    def letter(self) -> str:
        return self.name[0].upper()

    @property
    def quantity(self):
        """The value with its unit, as it is written: 10.7 kΩ, 22 nF, 5 V."""
        unit = _KINDS.get(self.letter, (None, None))[1]
        if self.value is None:
            return None
        return _engineering(ureg.Quantity(self.value, unit)) if unit else self.value

    def __str__(self) -> str:
        return self.text


@dataclass
class Model:
    name: str
    type: str
    params: dict[str, str] = field(default_factory=dict)


@dataclass
class Subcircuit:
    name: str
    ports: list[str]
    elements: list[Element] = field(default_factory=list)
    params: dict[str, str] = field(default_factory=dict)


def _logical_lines(text: str) -> list[str]:
    """Join ``+`` continuations; keep comments and blanks as they are."""
    out: list[str] = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        stripped = line.lstrip()
        if stripped.startswith("+") and out:
            out[-1] = out[-1] + " " + stripped[1:].strip()
        else:
            out.append(line.rstrip())
    return out


def _strip_comment(line: str) -> str:
    stripped = line.strip()
    if not stripped or stripped[0] == "*":
        return ""
    # `;` (LTspice, PSpice) and ` $ ` (ngspice) start comments outside braces
    depth = 0
    for i, ch in enumerate(stripped):
        if ch in "{(":
            depth += 1
        elif ch in "})":
            depth -= 1
        elif depth <= 0 and (ch == ";" or (ch == "$" and i and stripped[i - 1] in " \t")):
            return stripped[:i].rstrip()
    return stripped


def _tokens(line: str) -> list[str]:
    """Split on spaces, keeping ``{...}``, ``'...'`` and ``f(...)`` groups whole, and
    joining ``key = value`` into one token."""
    out, depth, cur, quote = [], 0, "", False
    for ch in line:
        if ch in "'\"" and depth == 0 and (not quote or ch == quote):
            quote = False if quote else ch
            cur += ch
        elif quote:
            cur += ch
        elif ch in "({":
            depth += 1
            cur += ch
        elif ch in ")}":
            depth -= 1
            cur += ch
        elif ch in " \t," and depth == 0:
            if cur:
                out.append(cur)
                cur = ""
        else:
            cur += ch
    if cur:
        out.append(cur)
    joined: list[str] = []
    i = 0
    while i < len(out):
        tok = out[i]
        if tok == "=" and joined and i + 1 < len(out):
            joined[-1] += "=" + out[i + 1]
            i += 2
            continue
        if tok.endswith("=") and i + 1 < len(out) and tok != "=":
            joined.append(tok + out[i + 1])
            i += 2
            continue
        if tok.startswith("=") and joined:
            joined[-1] += tok
            i += 1
            continue
        joined.append(tok)
        i += 1
    return joined


def _params(tokens) -> dict[str, str]:
    out = {}
    for tok in tokens:
        if "=" in tok:
            k, _, v = tok.partition("=")
            out[k.strip().lower()] = v.strip()
    return out


_MODEL = re.compile(r"(?i)^\.model\s+(\S+)\s+([A-Za-z_]\w*)\s*\(?(.*?)\)?\s*$")


@dataclass
class Directive:
    """A dot command: ``.tran 1u 2m`` is ``Directive("tran", ["1u", "2m"])``."""

    name: str
    args: list[str]
    text: str


class Netlist:
    """A SPICE netlist: elements, models, subcircuits, parameters and analyses.

    ``net["R1"]`` is an :class:`Element`; ``net.analyses`` the ``.tran``,
    ``.ac``, ``.dc`` and ``.op`` commands. ``net.with_values(R1=4.7 * kohm)``
    is a copy with new values, for :func:`simulate`.
    """

    def __init__(self, text: str, *, name: str = "", path: Path | None = None):
        self.name = name
        self.path = path
        self._lines = _logical_lines(text)
        self.title = self._lines[0].strip() if self._lines else ""
        self.elements: list[Element] = []
        self.models: dict[str, Model] = {}
        self.subcircuits: dict[str, Subcircuit] = {}
        self.params: dict[str, str] = {}
        self.directives: list[Directive] = []
        self.includes: list[str] = []
        self.control: list[str] = []
        self._where: dict[str, int] = {}  # element or parameter -> its line
        self._parse()

    @classmethod
    def load(cls, path) -> "Netlist":
        from .authoring import project_path
        path = project_path(path)
        text = path.read_bytes()
        decoded = (text.decode("utf-16") if text[:2] in (b"\xff\xfe", b"\xfe\xff")
                   else text.decode("utf-8", errors="replace"))
        return cls(decoded, name=path.stem, path=path)

    @classmethod
    def parse(cls, text: str, *, name: str = "") -> "Netlist":
        return cls(text, name=name)

    # parsing

    def _parse(self) -> None:
        sub: Subcircuit | None = None
        in_control = False
        # Models first, so a BJT's optional substrate node can be told from its model.
        for line in self._lines[1:]:
            m = _MODEL.match(_strip_comment(line))
            if m:
                params = {k.lower(): v for k, v in re.findall(r"(\w+)\s*=\s*([^\s=()]+)", m.group(3))}
                self.models[m.group(1).lower()] = Model(m.group(1), m.group(2).lower(), params)
        for index, line in enumerate(self._lines[1:], start=1):
            body = _strip_comment(line)
            if not body:
                continue
            low = body.lower()
            if in_control:
                if low.startswith(".endc"):
                    in_control = False
                else:
                    self.control.append(body)
                continue
            if low.startswith(".control"):
                in_control = True
                continue
            if low.startswith(".end") and not low.startswith((".ends", ".endc", ".endl")):
                break
            if body.startswith("."):
                toks = _tokens(body)
                name = toks[0][1:].lower()
                if name == "subckt" and len(toks) >= 2:
                    ports = [t for t in toks[2:] if "=" not in t and t.lower() != "params:"]
                    sub = Subcircuit(toks[1], ports, params=_params(toks[2:]))
                    self.subcircuits[toks[1].lower()] = sub
                elif name == "ends":
                    sub = None
                elif name == "param" and sub is None:
                    for k, v in _params(toks[1:]).items():
                        self.params[k] = v
                        self._where[k] = index
                elif name in ("include", "inc", "lib"):
                    if len(toks) >= 2:
                        self.includes.append(toks[1].strip("'\""))
                elif name != "model" and sub is None:
                    self.directives.append(Directive(name, toks[1:], body))
                continue
            element = self._element(body)
            if element is None:
                continue
            if sub is not None:
                sub.elements.append(element)
            else:
                self.elements.append(element)
                self._where[element.name.lower()] = index

    def _element(self, body: str) -> Element | None:
        toks = _tokens(body)
        name = toks[0]
        letter = name[0].upper()
        if letter not in _KINDS or len(toks) < 2:
            return None
        kind = _KINDS[letter][0]
        rest = toks[1:]
        if letter == "X":
            plain = [t for t in rest if "=" not in t and t.lower() != "params:"]
            model = plain[-1] if plain else None
            return Element(name, kind, plain[:-1], None, model, _params(rest), body)
        if letter == "K":
            value = _try_value(rest[-1]) if len(rest) >= 3 else None
            return Element(name, kind, rest[:-1], value, None, {}, body, rest[-1] if rest else "")
        if letter == "Q":
            count = 3
            if len(rest) >= 5 and rest[3].lower() not in self.models and rest[4].lower() in self.models:
                count = 4
            nodes, rest = rest[:count], rest[count:]
            model = rest[0] if rest else None
            return Element(name, kind, nodes, None, model, _params(rest[1:]), body)
        if letter == "A":
            model = rest[-1] if rest else None
            return Element(name, kind, rest[:-1], None, model, {}, body)
        count = _NODES.get(letter, 2)
        nodes, rest = rest[:count], rest[count:]
        if letter in "FHW" and rest:  # the controlling source comes next
            params = _params(rest)
            control = rest[0]
            value = _try_value(rest[1]) if len(rest) > 1 and letter in "FH" else None
            model = rest[1] if letter == "W" and len(rest) > 1 else None
            return Element(name, kind, nodes, value, model, {"control": control, **params}, body,
                           " ".join(rest[1:]))
        if letter in "RCL":
            params = _params(rest)
            plain = [t for t in rest if "=" not in t]
            spec = params.get({"R": "r", "C": "c", "L": "l"}[letter]) or (plain[0] if plain else "")
            value = _try_value(spec) if spec else None
            model = plain[0] if value is None and plain and not spec.startswith(("{", "'")) else None
            if model and model.lower() not in self.models:
                model = None
            return Element(name, kind, nodes, value, model, params, body, spec)
        if letter in "VI":
            spec = " ".join(rest)
            plain = [t for t in rest if "=" not in t]
            value = None
            if plain:
                if plain[0].lower() == "dc" and len(plain) > 1:
                    value = _try_value(plain[1])
                elif not plain[0].lower().startswith(("ac", "pulse", "sin", "pwl", "exp", "sffm", "am")):
                    value = _try_value(plain[0])
            return Element(name, kind, nodes, value, None, _params(rest), body, spec)
        if letter in "EG":
            plain = [t for t in rest if "=" not in t]
            value = _try_value(plain[0]) if len(plain) == 1 else None
            return Element(name, kind, nodes, value, None, _params(rest), body, " ".join(rest))
        if letter == "B":
            return Element(name, kind, nodes, None, None, _params(rest), body, " ".join(rest))
        model = next((t for t in rest if "=" not in t), None)
        return Element(name, kind, nodes, None, model, _params(rest), body)

    # access

    def __getitem__(self, name: str) -> Element:
        for e in self.elements:
            if e.name.lower() == name.lower():
                return e
        raise KeyError(f"no element {name!r} in this netlist; it has "
                       f"{', '.join(e.name for e in self.elements)}")

    def __contains__(self, name) -> bool:
        return any(e.name.lower() == str(name).lower() for e in self.elements)

    def __iter__(self):
        return iter(self.elements)

    def __len__(self) -> int:
        return len(self.elements)

    @property
    def nodes(self) -> list[str]:
        """Every node the top level joins, ground (``0``) last."""
        seen = dict.fromkeys(n for e in self.elements if e.letter not in "K" for n in e.nodes)
        ground = [n for n in seen if n.lower() in ("0", "gnd")]
        return sorted((n for n in seen if n not in ground), key=_natural) + ground

    @property
    def analyses(self) -> list[Directive]:
        return [d for d in self.directives
                if d.name in ("tran", "ac", "dc", "op", "noise", "tf", "pz", "sens", "disto", "sp")]

    @property
    def text(self) -> str:
        return "\n".join(self._lines) + "\n"

    def __str__(self) -> str:
        return self.text

    def with_values(self, **values) -> "Netlist":
        """A copy with new element values or ``.param`` values.

        ``net.with_values(R1=R_1, C2=C_2, Rf="10k")``: a quantity is written in
        the element's own unit (ohms, farads, henries, volts, amperes), a string
        as given. For a source, the string replaces its whole specification.
        """
        lines = list(self._lines)
        for key, new in values.items():
            index = self._where.get(key.lower())
            if index is None:
                raise KeyError(f"no element or .param named {key!r} in this netlist")
            if key.lower() in self.params and key.lower() not in [e.name.lower() for e in self.elements]:
                text = _spice_number(new, None)
                lines[index] = re.sub(rf"(?i)(\b{re.escape(key)}\s*=\s*)(\{{[^}}]*\}}|'[^']*'|\S+)",
                                      lambda m: m.group(1) + text, lines[index], count=1)
                continue
            element = self[key]
            unit = _KINDS[element.letter][1]
            text = _spice_number(new, unit)
            head = " ".join([element.name, *element.nodes])
            if element.letter in "VI" and isinstance(new, str):
                lines[index] = f"{head} {new}"
            elif element.letter in "RCLVIEG":
                params = " ".join(f"{k}={v}" for k, v in element.params.items()
                                  if k not in ("r", "c", "l"))
                if element.letter in "VI" and element.value_text:
                    spec = element.value_text
                    if re.match(r"(?i)(dc\s+)?[-+.\d{']", spec):
                        spec = re.sub(r"(?i)^(dc\s+)?\S+", lambda m: (m.group(1) or "") + text, spec, count=1)
                    else:
                        spec = f"DC {text} {spec}"
                    lines[index] = f"{head} {spec}"
                else:
                    lines[index] = f"{head} {text}" + (f" {params}" if params else "")
            else:
                raise ValueError(f"{element.name}: only R, C, L, sources and gains take a new value")
        return Netlist("\n".join(lines), name=self.name, path=self.path)

    def table(self, **options):
        """The elements as a table: reference, type, nodes and value."""
        from .content import Column, Table
        rows = []
        for e in self.elements:
            value = e.quantity if e.quantity is not None else (e.model or e.value_text or "")
            if isinstance(value, ureg.Quantity):
                value = fmt_quantity(_engineering(value))
            rows.append((e.name, e.kind, " ".join(e.nodes), str(value)))
        return Table([Column("ref", "Ref."), Column("kind", "Element"), Column("nodes", "Nodes"),
                      Column("value", "Value")], rows, **options)

    def simulate(self, **options) -> "Results":
        return simulate(self, **options)

    def kip_content(self, kind: str):
        return self.table() if kind == "table" else self

    def kip_summary(self) -> str:
        analyses = ", ".join("." + d.name for d in self.analyses) or "no analyses"
        return f"netlist {self.name or self.title}: {len(self.elements)} elements, {analyses}"


def _natural(name: str):
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", name)]


def _spice_number(value, unit) -> str:
    if isinstance(value, ureg.Quantity):
        value = value.to(unit).magnitude if unit else value.to_base_units().magnitude
    if isinstance(value, str):
        return value
    return f"{float(value):.6g}"


def read_netlist(path):
    """A netlist file: SPICE (``.cir``, ``.sp``, ``.spice``, ``.net``, ``.cdl``) as a
    :class:`Netlist`, or a KiCad netlist -- as Eeschema and SKiDL write -- as a
    :class:`~kip.schematic.KicadNetlist` of parts and nets."""
    from .authoring import project_path
    resolved = project_path(path)
    if resolved.read_bytes()[:64].lstrip().startswith(b"(export"):
        from .schematic import KicadNetlist
        return KicadNetlist.load(resolved)
    return Netlist.load(resolved)

# -- simulation -------------------------------------------------------------------------


def _ngspice() -> str | None:
    override = os.environ.get("KIP_NGSPICE")
    if override:
        return override
    names = ("ngspice_con", "ngspice") if os.name == "nt" else ("ngspice",)
    return next((p for p in map(shutil.which, names) if p), None)


def _absolute_includes(text: str, base: Path | None) -> tuple[str, list[Path]]:
    found: list[Path] = []
    if base is None:
        return text, found

    def fix(m):
        target = m.group(3)
        path = Path(target)
        if not path.is_absolute():
            path = (base / path).resolve()
        if path.exists():
            found.append(path)
            return f"{m.group(1)}{m.group(2)}{path.as_posix()}{m.group(2)}"
        return m.group(0)

    return re.sub(r"(?im)^(\s*\.(?:include|inc|lib)\s+)(['\"]?)([^'\"\s]+)\2", fix, text), found


def simulate(netlist, *, cache=None, timeout: float = 120) -> "Results":
    """Run a netlist with ngspice and read back every analysis.

    ``netlist`` is a :class:`Netlist`, a netlist file, or netlist text. The
    analyses are the netlist's own (``.tran``, ``.ac``, ``.dc``, ``.op``,
    ``.noise``). A netlist with a ``.control`` block runs as written and its
    results are read from the raw files that block writes.

    ``cache="output/filter.raw"`` keeps the results: the next build reuses
    them while the netlist (and every file it includes) is unchanged, and a
    machine without ngspice builds from them.
    """
    from .authoring import project_path
    if isinstance(netlist, Netlist):
        net = netlist
    elif isinstance(netlist, Path) or (isinstance(netlist, str) and "\n" not in netlist
                                       and project_path(netlist).exists()):
        net = Netlist.load(netlist)
    else:
        net = Netlist(str(netlist))
    text, included = _absolute_includes(net.text, net.path.parent if net.path else None)
    if not re.search(r"(?im)^\s*\.end\s*$", text):
        text += ".end\n"
    # The tag names the netlist as written and what it includes, not where the
    # project sits or how its lines end: a copied project keeps its cache.
    digest = hashlib.sha256(re.sub(r"\r\n?", "\n", net.text).strip().encode("utf-8"))
    for path in included:
        digest.update(re.sub(rb"\r\n?", b"\n", path.read_bytes()))
    tag = f"kip-{digest.hexdigest()[:16]}"
    cached = project_path(cache) if cache else None
    if cached is not None and cached.exists():
        results = read_raw(cached)
        if results and tag in results.title.lower():
            return results

    exe = _ngspice()
    if exe is None:
        why = ("its cached results are for a different netlist" if cached is not None and cached.exists()
               else "nothing is cached for it")
        raise RuntimeError(f"simulating {net.name or 'this netlist'} needs ngspice, which is not "
                           f"installed, and {why}: install ngspice (ngspice.sourceforge.io), "
                           "or set KIP_NGSPICE to its path")
    lines = text.split("\n")
    lines[0] = f"{lines[0]} {tag}"
    text = "\n".join(lines)
    # A .control block that runs no analysis (KiCad writes one that prints the
    # version) would stop ngspice running the netlist's own; it goes.
    has_control = any(re.match(r"(run|tran|ac|dc|op|noise|tf|pz|sens|sp|disto)\b", c.strip().lower())
                      for c in net.control)
    if net.control and not has_control:
        text = re.sub(r"(?ims)^\s*\.control\b.*?^\s*\.endc\b[^\n]*\n?", "", text)
    with tempfile.TemporaryDirectory(prefix="kip-spice-") as tmp:
        work = Path(tmp)
        (work / "circuit.cir").write_text(text, encoding="utf-8")
        args = [exe, "-b", "circuit.cir"] if has_control else [exe, "-b", "-r", "results.raw", "circuit.cir"]
        try:
            run = subprocess.run(args, cwd=work, capture_output=True, text=True, timeout=timeout,
                                 errors="replace")
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"ngspice took longer than {timeout:g} s; raise simulate(timeout=...)") from None
        raws = sorted(work.glob("*.raw"), key=lambda p: p.stat().st_mtime)
        log = (run.stdout or "") + (run.stderr or "")
        problems = [line.strip() for line in log.splitlines()
                    if re.match(r"\s*(error|fatal)\b", line, re.I) or "error on line" in line.lower()]
        if not raws or (run.returncode and problems):
            detail = "; ".join(dict.fromkeys(problems)) or log.strip().splitlines()[-1:] or ["no output"]
            raise RuntimeError(f"ngspice failed: {detail if isinstance(detail, str) else detail[0]}")
        results = Results([a for raw in raws for a in read_raw(raw)])
        results.title = f"{net.title} {tag}"
        results.log = log
        if cached is not None:
            cached.parent.mkdir(parents=True, exist_ok=True)
            data = b"".join(raw.read_bytes() for raw in raws)
            # Stamp the tag into each title so a later build can recognise them.
            data = re.sub(rb"(?m)^Title: ([^\n]*)", lambda m: b"Title: " + m.group(1).split(b" kip-")[0]
                          + b" " + tag.encode(), data)
            cached.write_bytes(data)
    return results

# -- raw files ---------------------------------------------------------------------------

#: Vector types and their units, as ngspice and LTspice name them.
_TYPE_UNITS = {"time": "s", "frequency": "Hz", "voltage": "V", "current": "A",
               "device_current": "A", "subckt_current": "A", "voltage-density": "V/Hz**0.5",
               "current-density": "A/Hz**0.5", "temperature": "degC", "impedance": "ohm",
               "admittance": "S", "power": "W"}
_KIND = {"transient": "tran", "ac": "ac", "dc": "dc", "operating": "op", "noise": "noise",
         "transfer": "tf", "pole": "pz", "sensitivity": "sens", "s-param": "sp"}


def _kind(plotname: str) -> str:
    low = plotname.lower()
    for word, kind in _KIND.items():
        if word in low:
            return kind
    return low.split()[0] if low else ""


def read_raw(path) -> "Results":
    """A SPICE raw file -- ngspice, Xyce or LTspice; binary or ASCII -- or the text
    LTspice exports from a waveform window. Every analysis in it is read."""
    from .authoring import project_path
    path = project_path(path)
    data = path.read_bytes()
    if data[:2] in (b"\xff\xfe",) or (len(data) > 1 and data[1:2] == b"\x00" and data[:1].isalpha()):
        return _read_raw(data, utf16=True, name=path.stem)
    if data.lstrip()[:6].lower() == b"title:" or b"\nPlotname:" in data[:4000]:
        return _read_raw(data, utf16=False, name=path.stem)
    return _read_text_export(data.decode("utf-8", errors="replace"), name=path.stem)


def _read_raw(data: bytes, *, utf16: bool, name: str) -> "Results":
    import numpy as np

    plots: list[Analysis] = []
    pos = 0
    title = ""
    width = 2 if utf16 else 1
    encoding = "utf-16-le" if utf16 else "latin-1"
    if utf16 and data[:2] == b"\xff\xfe":
        pos = 2
    while pos < len(data):
        header: dict[str, str] = {}
        variables: list[tuple[str, str]] = []
        mode = None
        while pos < len(data):
            end = data.find("\n".encode(encoding), pos)
            if utf16:
                while end != -1 and (end - pos) % 2:
                    end = data.find(b"\n\x00", end + 1)
            if end == -1:
                pos = len(data)
                break
            line = data[pos:end].decode(encoding, errors="replace").rstrip("\r")
            pos = end + width
            if not line.strip() and not header:
                continue
            key, _, value = line.partition(":")
            low = key.strip().lower()
            if low == "variables":
                count = int(header.get("no. variables", "0"))
                for _ in range(count):
                    end = data.find("\n".encode(encoding), pos)
                    if utf16:
                        while end != -1 and (end - pos) % 2:
                            end = data.find(b"\n\x00", end + 1)
                    vline = data[pos:end].decode(encoding, errors="replace").split()
                    pos = end + width
                    variables.append((vline[1], vline[2] if len(vline) > 2 else ""))
                continue
            if low in ("binary", "values"):
                mode = low
                break
            header[low] = value.strip()
        if mode is None:
            break
        title = title or header.get("title", "")
        flags = header.get("flags", "").lower().split()
        npoints = int(header.get("no. points", "0"))
        nvars = len(variables)
        complex_ = "complex" in flags
        ltspice = "offset" in header or "ltspice" in header.get("command", "").lower() or utf16
        if mode == "binary":
            if complex_:
                size = npoints * nvars * 16
                arr = np.frombuffer(data, dtype="<f8", count=npoints * nvars * 2, offset=pos)
                if "fastaccess" in flags:
                    arr = arr.reshape(nvars, npoints, 2).transpose(1, 0, 2)
                values = arr.reshape(npoints, nvars, 2)
                values = values[..., 0] + 1j * values[..., 1]
            elif ltspice and "double" not in flags:
                # LTspice: the scale in doubles, every other vector in singles
                rec = np.dtype([("x", "<f8")] + [(f"v{k}", "<f4") for k in range(1, nvars)])
                size = npoints * rec.itemsize
                arr = np.frombuffer(data, dtype=rec, count=npoints, offset=pos)
                values = np.column_stack([np.abs(arr["x"])] + [arr[f"v{k}"].astype(float)
                                                                for k in range(1, nvars)])
            else:
                size = npoints * nvars * 8
                values = np.frombuffer(data, dtype="<f8", count=npoints * nvars, offset=pos)
                values = (values.reshape(nvars, npoints).T if "fastaccess" in flags
                          else values.reshape(npoints, nvars))
                if ltspice:
                    values = values.copy()
                    values[:, 0] = np.abs(values[:, 0])
            pos += size
        else:
            numbers: list = []
            want = npoints * nvars
            while len(numbers) < want + npoints and pos < len(data):
                end = data.find("\n".encode(encoding), pos)
                if end == -1:
                    end = len(data)
                line = data[pos:end].decode(encoding, errors="replace").strip()
                if line and (":" in line and line.split(":")[0].lower() in ("title", "plotname", "flags",
                                                                             "date", "command")):
                    break
                pos = end + width
                if not line:
                    continue
                numbers.extend(line.split())
            values = _ascii_values(numbers, npoints, nvars, complex_)
        names = [v[0] for v in variables]
        units = [_TYPE_UNITS.get(v[1].lower(), "") for v in variables]
        plots.append(Analysis(header.get("plotname", ""), names, units, values, title=title))
    results = Results(plots)
    results.title = title
    results.name = name
    return results


def _ascii_values(tokens, npoints, nvars, complex_):
    import numpy as np
    out = np.zeros((npoints, nvars), dtype=complex if complex_ else float)
    i = 0
    for p in range(npoints):
        i += 1  # the point index
        for v in range(nvars):
            tok = tokens[i]
            i += 1
            if complex_:
                re_, _, im = tok.partition(",")
                out[p, v] = complex(float(re_), float(im or 0))
            else:
                out[p, v] = float(tok)
    return out


_POLAR = re.compile(r"\(([-+0-9.eE]+)dB,([-+0-9.eE]+)°?\)")


def _read_text_export(text: str, *, name: str) -> "Results":
    """LTspice's *File > Export data as text*: a header row, then tab-separated values;
    AC points as ``(mag dB, phase°)`` or ``re,im``."""
    import numpy as np
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        raise ValueError("empty waveform file")
    header = re.split(r"\t|,(?![^(]*\))", lines[0].strip())
    names = [h.strip() for h in header]
    rows = []
    is_complex = False
    for line in lines[1:]:
        if line.lower().startswith("step information"):
            continue
        cells = line.strip().split("\t")
        row = []
        for cell in cells:
            m = _POLAR.fullmatch(cell.strip())
            if m:
                mag = 10 ** (float(m.group(1)) / 20)
                row.append(mag * np.exp(1j * math.radians(float(m.group(2)))))
                is_complex = True
            elif "," in cell:
                re_, im = cell.split(",", 1)
                row.append(complex(float(re_), float(im)))
                is_complex = True
            else:
                row.append(float(cell))
        rows.append(row)
    values = np.array(rows, dtype=complex if is_complex else float)
    if is_complex:
        values[:, 0] = values[:, 0].real
    first = names[0].lower()
    kind = "AC Analysis" if first.startswith("freq") else ("Transient Analysis" if first == "time"
                                                          else "DC transfer characteristic")
    units = [("Hz" if first.startswith("freq") else "s" if first == "time" else "")]
    units += ["A" if n.lower().startswith("i") else "V" if n.lower().startswith("v") else ""
              for n in names[1:]]
    names[0] = "frequency" if first.startswith("freq") else names[0]
    results = Results([Analysis(kind, names, units, values)])
    results.name = name
    return results

# -- results -------------------------------------------------------------------------


class Analysis:
    """One analysis from a raw file: its vectors against the sweep."""

    def __init__(self, plotname: str, names, units, values, *, title: str = ""):
        import numpy as np
        self.plotname = plotname
        self.kind = _kind(plotname)
        self.names = list(names)
        self.units = list(units)
        self.values = np.asarray(values)
        self.title = title

    def __len__(self) -> int:
        return len(self.values)

    def _index(self, name: str) -> int:
        want = name.strip().lower()
        candidates = [want]
        m = re.fullmatch(r"([vi])\((.+)\)", want)
        if m:
            candidates += [m.group(2), f"{m.group(2)}#branch" if m.group(1) == "i" else m.group(2)]
        else:
            candidates += [f"v({want})", f"i({want})", f"{want}#branch"]
        lowered = [n.lower() for n in self.names]
        for c in candidates:
            if c in lowered:
                return lowered.index(c)
        # KiCad names a net by its sheet path: v(out) is v(/out), or v(/filter/out)
        node = m.group(2) if m else want
        nested = [k for k, n in enumerate(lowered) if re.fullmatch(rf"(?:[vi]\()?\S*/{re.escape(node)}\)?", n)]
        if len(nested) == 1:
            return nested[0]
        raise KeyError(f"no vector {name!r} in the {self.plotname or 'analysis'}; it has "
                       f"{', '.join(self.names)}")

    def _quantity(self, k: int):
        column = self.values[:, k]
        if self.kind == "op" or len(column) == 1:
            value = column[0]
            value = value.real if not isinstance(value, float) and value.imag == 0 else value
            return ureg.Quantity(float(value) if isinstance(value, float) else value,
                                 self.units[k] or "dimensionless")
        if self.kind in ("tran", "dc") and column.dtype.kind == "c":
            column = column.real
        return ureg.Quantity(column, self.units[k] or "dimensionless")

    @property
    def x(self):
        """The sweep: time, frequency, or the swept source's value."""
        import numpy as np
        column = self.values[:, 0]
        if column.dtype.kind == "c":
            column = np.real(column)
        return ureg.Quantity(column, self.units[0] or "dimensionless")

    @property
    def time(self):
        return self.x

    @property
    def frequency(self):
        return self.x

    def __getitem__(self, name: str):
        k = self._index(name)
        q = self._quantity(k)
        if self.kind == "op" or len(self.values) == 1:
            return q
        return Signal(self.x, q, name=self.names[k], xname=self.names[0])

    def __contains__(self, name) -> bool:
        try:
            self._index(str(name))
            return True
        except KeyError:
            return False

    def v(self, node: str, reference: str | None = None):
        """The voltage of ``node``, or ``v("a", "b")`` for a - b."""
        if reference is not None:
            return self[f"v({node})"] - self[f"v({reference})"]
        return self[f"v({node})"]

    def i(self, device: str):
        """The current through a voltage source or inductor: ``i("V1")``."""
        return self[f"i({device})"]

    def table(self, **options):
        """An operating point as a table of node voltages and branch currents."""
        from .content import Column, Table
        rows = []
        for k, name in enumerate(self.names):
            if k == 0 and self.kind != "op":
                continue
            q = self._quantity(k)
            if getattr(q, "ndim", 0):
                q = q[-1]
            rows.append((name, fmt_quantity(_engineering(q))))
        return Table([Column("name", "Vector"), Column("value", "Value", align="right")], rows, **options)

    def kip_content(self, kind: str):
        return self.table() if kind == "table" else self

    def kip_summary(self) -> str:
        return f"{self.plotname}: {len(self.values)} points of {', '.join(self.names)}"

    def __repr__(self) -> str:
        return f"<Analysis {self.plotname!r} {len(self.values)} points>"


class Results(list):
    """Every analysis of a simulation: ``results.tran``, ``results.ac``, ``results.op``."""

    title = ""
    name = ""
    log = ""

    def _first(self, kind: str) -> Analysis:
        for a in self:
            if a.kind == kind:
                return a
        raise AttributeError(f"these results have no {kind} analysis; they have "
                             f"{', '.join(a.kind for a in self) or 'none'}")

    @property
    def tran(self) -> Analysis:
        return self._first("tran")

    @property
    def ac(self) -> Analysis:
        return self._first("ac")

    @property
    def dc(self) -> Analysis:
        return self._first("dc")

    @property
    def op(self) -> Analysis:
        return self._first("op")

    @property
    def noise(self) -> Analysis:
        return self._first("noise")

    def __getitem__(self, key):
        if isinstance(key, str):
            return self._first(key)
        return super().__getitem__(key)

    def kip_summary(self) -> str:
        names = {"tran": "transient", "ac": "AC", "dc": "DC sweep", "op": "operating point",
                 "noise": "noise", "tf": "transfer function", "sp": "S-parameter"}
        parts = [names.get(a.kind, a.kind) + (f" ({len(a)} points)" if len(a) > 1 else "") for a in self]
        return "simulated " + ", ".join(parts)

# -- signals --------------------------------------------------------------------------

#: The half-power point, 20·log10(1/√2): what "the -3 dB point" means.
HALF_POWER = -20 * math.log10(math.sqrt(2))

_PREFIXES = [(1e9, "G"), (1e6, "M"), (1e3, "k"), (1.0, ""), (1e-3, "m"), (1e-6, "u"), (1e-9, "n"),
             (1e-12, "p"), (1e-15, "f")]
_SCALABLE = {"second": "s", "hertz": "Hz", "volt": "V", "ampere": "A", "ohm": "ohm", "watt": "W",
             "farad": "F", "henry": "H", "siemens": "S"}


def _engineering(q):
    """``q`` in the prefixed unit that puts its largest magnitude between 1 and
    1000: 2.2e-6 s is 2.2 µs, 15900 Ω is 15.9 kΩ."""
    import numpy as np
    if not isinstance(q, ureg.Quantity) or q.dimensionless:
        return q
    base = next((symbol for name, symbol in _SCALABLE.items()
                 if q.dimensionality == ureg.Unit(name).dimensionality), None)
    if base is None:
        return q
    q = q.to(base)
    mags = np.abs(np.atleast_1d(np.asarray(q.magnitude)))
    mags = mags[np.isfinite(mags) & (mags > 0)]
    if not len(mags):
        return q
    big = float(mags.max())
    prefix = next((p for factor, p in _PREFIXES if big >= factor * 0.9995), "f")
    q = q.to(prefix + base)
    if np.ndim(q.magnitude) == 0 and isinstance(q.magnitude, float):  # 10.7 kΩ, not 10.700000000000001
        q = ureg.Quantity(float(f"{q.magnitude:.12g}"), q.units)
    return q


class Signal:
    """A vector against its sweep -- ``v(out)`` over time, a gain over frequency.

    ``x`` and ``y`` are quantities; an AC signal's ``y`` is complex. Measurements
    return quantities: ``rise_time()``, ``overshoot()``, ``settling_time()``,
    ``cutoff()``, ``bandwidth()``, ``phase_margin()``, ``at(x)``...
    Dividing two signals gives a transfer function: ``ac.v("out") / ac.v("in")``.
    """

    def __init__(self, x, y, *, name: str = "", xname: str = ""):
        import numpy as np
        if not isinstance(x, ureg.Quantity):
            x = ureg.Quantity(np.asarray(x, dtype=float), "dimensionless")
        if not isinstance(y, ureg.Quantity):
            y = ureg.Quantity(np.asarray(y), "dimensionless")
        if len(x.magnitude) != len(y.magnitude):
            raise ValueError("a signal's x and y must have the same length")
        self.x, self.y = x, y
        self.name, self.xname = name, xname

    # basics

    @property
    def _xm(self):
        return self.x.magnitude

    @property
    def _ym(self):
        return self.y.magnitude

    @property
    def is_complex(self) -> bool:
        return self._ym.dtype.kind == "c"

    @property
    def is_frequency(self) -> bool:
        return self.x.check("[frequency]")

    def __len__(self) -> int:
        return len(self._xm)

    def __repr__(self) -> str:
        return f"<Signal {self.name} {len(self)} points>"

    def __str__(self) -> str:
        """How a calc row shows it: its points and sweep."""
        x0, x1 = (fmt_quantity(_engineering(self._xq(float(v)))) for v in (self._xm[0], self._xm[-1]))
        return f"{len(self)} points, {x0} to {x1}"

    def _real(self, what: str):
        import numpy as np
        if self.is_complex:
            if np.allclose(self._ym.imag, 0):
                return self._ym.real
            raise ValueError(f"{what} needs a real signal; take .magnitude(), .db() or .phase() of "
                             f"{self.name or 'this AC signal'} first")
        return self._ym

    def _q(self, value):
        return ureg.Quantity(value, self.y.units)

    def _xq(self, value):
        return ureg.Quantity(value, self.x.units)

    def _level(self, level):
        if isinstance(level, ureg.Quantity):
            return level.to(self.y.units).magnitude
        return float(level)

    def _xval(self, x0):
        if isinstance(x0, ureg.Quantity):
            return x0.to(self.x.units).magnitude
        return float(x0)

    def _new(self, y, name, units=None):
        return Signal(self.x, ureg.Quantity(y, units if units is not None else self.y.units),
                      name=name, xname=self.xname)

    # arithmetic

    def _other(self, other):
        import numpy as np
        if isinstance(other, Signal):
            if len(other) == len(self) and np.allclose(other._xm, self.x.to(other.x.units).magnitude):
                return other.y
            raise ValueError("these signals are sampled at different points; take them from one analysis")
        return other

    def __truediv__(self, other):
        y = self.y / self._other(other)
        return Signal(self.x, y, name=f"{self.name}/{getattr(other, 'name', other)}", xname=self.xname)

    def __mul__(self, other):
        return Signal(self.x, self.y * self._other(other), name=self.name, xname=self.xname)

    __rmul__ = __mul__

    def __add__(self, other):
        return Signal(self.x, self.y + self._other(other), name=self.name, xname=self.xname)

    def __sub__(self, other):
        name = f"{self.name}-{other.name}" if isinstance(other, Signal) else self.name
        return Signal(self.x, self.y - self._other(other), name=name, xname=self.xname)

    def __neg__(self):
        return Signal(self.x, -self.y, name=f"-{self.name}", xname=self.xname)

    def __abs__(self):
        return self.magnitude()

    # views

    def magnitude(self) -> "Signal":
        import numpy as np
        return self._new(np.abs(self._ym), f"|{self.name}|")

    def real(self) -> "Signal":
        return self._new(self._ym.real, f"Re {self.name}")

    def imag(self) -> "Signal":
        return self._new(self._ym.imag, f"Im {self.name}")

    def db(self) -> "Signal":
        """20·log10 of the magnitude: a gain in dB (dBV for a voltage)."""
        import numpy as np
        with np.errstate(divide="ignore"):
            return self._new(20 * np.log10(np.abs(self._ym)), f"{self.name} (dB)", "dimensionless")

    def phase(self, *, unwrap: bool = True) -> "Signal":
        """The phase in degrees, unwrapped so it runs continuously."""
        import numpy as np
        angle = np.angle(self._ym)
        if unwrap:
            angle = np.unwrap(angle)
        return self._new(np.degrees(angle), f"phase {self.name}", "degree")

    def window(self, start=None, stop=None) -> "Signal":
        """The part between ``start`` and ``stop`` (sweep values, with units)."""
        import numpy as np
        xm = self._xm
        lo = self._xval(start) if start is not None else xm[0]
        hi = self._xval(stop) if stop is not None else xm[-1]
        inside = (xm >= lo) & (xm <= hi)
        xs = list(xm[inside])
        ys = list(self._ym[inside])
        if start is not None and (not xs or xs[0] > lo):
            xs.insert(0, lo)
            ys.insert(0, self._interp(lo))
        if stop is not None and (not xs or xs[-1] < hi):
            xs.append(hi)
            ys.append(self._interp(hi))
        return Signal(self._xq(np.array(xs)), self._q(np.array(ys)), name=self.name, xname=self.xname)

    # values

    def _interp(self, x0: float):
        import numpy as np
        if self.is_complex:
            return complex(np.interp(x0, self._xm, self._ym.real), np.interp(x0, self._xm, self._ym.imag))
        return float(np.interp(x0, self._xm, self._ym))

    def at(self, x0):
        """The value at sweep point ``x0``, interpolated: ``H.at(1 * kHz)``."""
        x = self._xval(x0)
        if not self._xm[0] <= x <= self._xm[-1]:
            raise ValueError(f"{fmt_quantity(_engineering(self._xq(x)))} is outside this signal's sweep, "
                             f"{fmt_quantity(_engineering(self._xq(self._xm[0])))} to "
                             f"{fmt_quantity(_engineering(self._xq(self._xm[-1])))}")
        return self._q(self._interp(x))

    @property
    def initial(self):
        return self._q(self._ym[0])

    @property
    def final(self):
        return self._q(self._ym[-1])

    def max(self):
        return self._q(float(self._real("max()").max()))

    def min(self):
        return self._q(float(self._real("min()").min()))

    def peak(self):
        """The largest magnitude."""
        import numpy as np
        return self._q(float(np.abs(self._ym).max()))

    def argmax(self):
        """The sweep point of the largest value (largest magnitude for an AC signal)."""
        import numpy as np
        y = np.abs(self._ym) if self.is_complex else self._ym
        return self._xq(float(self._xm[int(np.argmax(y))]))

    def argmin(self):
        import numpy as np
        y = np.abs(self._ym) if self.is_complex else self._ym
        return self._xq(float(self._xm[int(np.argmin(y))]))

    def peak_to_peak(self):
        y = self._real("peak_to_peak()")
        return self._q(float(y.max() - y.min()))

    def mean(self):
        """The average over the sweep, weighted by the step (simulators step unevenly)."""
        import numpy as np
        y, x = self._real("mean()"), self._xm
        span = x[-1] - x[0]
        if span <= 0:
            return self._q(float(y.mean()))
        return self._q(float(np.trapezoid(y, x) / span))

    def rms(self):
        import numpy as np
        y, x = self._real("rms()"), self._xm
        span = x[-1] - x[0]
        if span <= 0:
            return self._q(float(np.sqrt(np.mean(y ** 2))))
        return self._q(float(np.sqrt(np.trapezoid(y ** 2, x) / span)))

    # crossings and edges

    def crossings(self, level, *, edge: str = "either") -> list:
        """Every sweep point where the signal crosses ``level``, interpolated."""
        import numpy as np
        if edge not in ("rising", "falling", "either"):
            raise ValueError("edge is 'rising', 'falling' or 'either'")
        y, x = self._real("crossings()") - self._level(level), self._xm
        out = []
        for i in np.nonzero(np.diff(np.sign(y)) != 0)[0]:
            rising = y[i + 1] > y[i]
            if (edge == "rising" and not rising) or (edge == "falling" and rising):
                continue
            if y[i] == 0 and i and np.sign(y[i - 1]) == np.sign(y[i + 1]):
                continue
            t = x[i] if y[i + 1] == y[i] else x[i] - y[i] * (x[i + 1] - x[i]) / (y[i + 1] - y[i])
            if not out or t != out[-1]:
                out.append(t)
        return [self._xq(float(t)) for t in out]

    def crossing(self, level, *, n: int = 1, edge: str = "either"):
        """The ``n``-th crossing of ``level``: ``v.crossing(1.65 * V, edge="rising")``."""
        found = self.crossings(level, edge=edge)
        if len(found) < n:
            raise ValueError(f"{self.name or 'the signal'} crosses {fmt_quantity(self._q(self._level(level)))} "
                             f"{len(found)} time{'s' if len(found) != 1 else ''} ({edge}), not {n}")
        return found[n - 1]

    def _step(self):
        """(base, top, rising): a step's initial and final values, else its extremes."""
        y = self._real("a step measurement")
        lo, hi = float(y.min()), float(y.max())
        first, last = float(y[0]), float(y[-1])
        if abs(last - first) > 0.5 * (hi - lo):
            return first, last, last > first
        return lo, hi, True

    def rise_time(self, low: float = 0.1, high: float = 0.9):
        """From ``low`` to ``high`` of the step (10 % to 90 % by default)."""
        base, top, rising = self._step()
        if not rising:
            raise ValueError(f"{self.name or 'the signal'} falls; use fall_time()")
        t1 = self.crossing(base + low * (top - base), edge="rising")
        later = [t for t in self.crossings(base + high * (top - base), edge="rising") if t >= t1]
        if not later:
            raise ValueError(f"{self.name or 'the signal'} never reaches {high:.0%} of its step")
        return (later[0] - t1).to(self.x.units)

    def fall_time(self, high: float = 0.9, low: float = 0.1):
        y = self._real("fall_time()")
        first, last = float(y[0]), float(y[-1])
        lo, hi = float(y.min()), float(y.max())
        top, base = (first, last) if abs(last - first) > 0.5 * (hi - lo) else (hi, lo)
        t1 = self.crossing(base + high * (top - base), edge="falling")
        later = [t for t in self.crossings(base + low * (top - base), edge="falling") if t >= t1]
        if not later:
            raise ValueError(f"{self.name or 'the signal'} never falls to {low:.0%} of its step")
        return (later[0] - t1).to(self.x.units)

    def overshoot(self):
        """How far the step goes past its final value, as a percentage of the step."""
        y = self._real("overshoot()")
        first, last = float(y[0]), float(y[-1])
        step = last - first
        if abs(step) <= 0.5 * float(y.max() - y.min()):
            raise ValueError(f"{self.name or 'the signal'} is not a step: it ends near where it "
                             "started; measure one edge with .window(start, stop).overshoot()")
        beyond = (y.max() - last) if step > 0 else (last - y.min())
        return ureg.Quantity(max(0.0, float(beyond / abs(step))) * 100, "percent")

    def settling_time(self, tolerance: float = 0.02, *, start=None):
        """Time from ``start`` (the start of the sweep) until the signal stays within
        ``tolerance`` of the step of its final value."""
        import numpy as np
        y, x = self._real("settling_time()"), self._xm
        first, last = float(y[0]), float(y[-1])
        band = tolerance * abs(last - first) if last != first else tolerance * abs(last)
        outside = np.nonzero(np.abs(y - last) > band)[0]
        t0 = self._xval(start) if start is not None else x[0]
        if not len(outside):
            return self._xq(0.0)
        i = outside[-1]
        if i + 1 >= len(x):
            raise ValueError(f"{self.name or 'the signal'} has not settled within {tolerance:.0%} "
                             "by the end of the simulation")
        # interpolate where it enters the band for good
        target = last + band * np.sign(y[i] - last)
        t = x[i] + (target - y[i]) * (x[i + 1] - x[i]) / (y[i + 1] - y[i]) if y[i + 1] != y[i] else x[i + 1]
        return self._xq(float(max(0.0, t - t0)))

    def period(self):
        """The mean spacing of rising crossings of the middle level."""
        y = self._real("period()")
        mid = (float(y.max()) + float(y.min())) / 2
        edges = [t.magnitude for t in self.crossings(mid, edge="rising")]
        if len(edges) < 2:
            raise ValueError(f"{self.name or 'the signal'} does not complete a cycle")
        return self._xq((edges[-1] - edges[0]) / (len(edges) - 1))

    def frequency(self):
        return (1 / self.period()).to("Hz")

    # frequency response

    def _gain_db(self):
        import numpy as np
        with np.errstate(divide="ignore"):
            return 20 * np.log10(np.abs(self._ym))

    def cutoff(self, level: float = HALF_POWER):
        """Where the gain first falls ``level`` dB (-3 by default) from the passband.

        A response that starts high (a low-pass) is measured from its low-frequency
        gain; one that starts low (a high-pass) from its high-frequency gain.
        """
        g, x = self._gain_db(), self._xm
        if g[0] >= g[-1]:
            ref = g[0] + level
            idx = [i for i in range(len(g) - 1) if g[i] >= ref > g[i + 1]]
            if not idx:
                raise ValueError(f"the gain never falls {abs(level):g} dB below its "
                                 "low-frequency value in this sweep")
            i = idx[0]
        else:
            ref = g[-1] + level
            idx = [i for i in range(len(g) - 1) if g[i] < ref <= g[i + 1]]
            if not idx:
                raise ValueError(f"the gain never rises to {abs(level):g} dB below its "
                                 "high-frequency value in this sweep")
            i = idx[-1]
        return self._xq(_cross(x, g, i, ref))

    def bandwidth(self, level: float = HALF_POWER):
        """The -3 dB bandwidth: the cut-off of a low-pass, or for a response that peaks
        inside the sweep the width between the points ``level`` dB below the peak."""
        import numpy as np
        g, x = self._gain_db(), self._xm
        k = int(np.argmax(g))
        if 0 < k < len(g) - 1 and g[0] < g[k] + level and g[-1] < g[k] + level:
            ref = g[k] + level
            lo = max(i for i in range(k) if g[i] < ref)
            hi = min(i for i in range(k, len(g)) if g[i] < ref)
            f_lo = _cross(x, g, lo, ref)
            f_hi = _cross(x, g, hi - 1, ref)
            return self._xq(f_hi - f_lo)
        return self.cutoff(level)

    def gain_at(self, f):
        """The gain in dB at frequency ``f``."""
        import numpy as np
        x = self._xval(f)
        g = self._gain_db()
        return float(np.interp(math.log10(x), np.log10(self._xm), g))

    def unity_gain_frequency(self):
        """Where the magnitude falls through 1 (0 dB): a loop's crossover."""
        g, x = self._gain_db(), self._xm
        idx = [i for i in range(len(g) - 1) if g[i] >= 0 > g[i + 1]]
        if not idx:
            raise ValueError(f"{self.name or 'the loop gain'} never falls through 0 dB in this sweep")
        i = idx[0]
        return self._xq(_cross(x, g, i, 0.0))

    def _loop_phase(self):
        """The unwrapped phase in degrees, starting within ±180°."""
        import numpy as np
        phase = np.degrees(np.unwrap(np.angle(self._ym)))
        return phase - 360 * round(float(phase[0]) / 360)

    def phase_margin(self):
        """180° plus the loop's phase where its gain is 0 dB."""
        import numpy as np
        f = self.unity_gain_frequency().magnitude
        phase = self._loop_phase()
        at = float(np.interp(math.log10(f), np.log10(self._xm), phase))
        return ureg.Quantity(180 + at, "degree")

    def gain_margin(self) -> float:
        """How far the gain is below 0 dB where the phase reaches -180°, in dB."""
        import numpy as np
        phase = self._loop_phase()
        g, x = self._gain_db(), self._xm
        idx = [i for i in range(len(phase) - 1) if phase[i] > -180 >= phase[i + 1]]
        if not idx:
            raise ValueError(f"the phase of {self.name or 'the loop gain'} never reaches -180° in this sweep")
        i = idx[0]
        fx = _cross(x, phase, i, -180.0)
        return -float(np.interp(math.log10(fx), np.log10(x), g))

    # display

    def kip_series(self):
        """What :func:`kip.plot` draws: the gain in dB on a log axis for an AC
        signal, the values in a readable unit otherwise."""
        y_name = self.name or "value"
        x, xscale = self._sweep_axis()
        if self.is_complex:
            ylabel = "Magnitude (dB)" if re.fullmatch(r"S\d\d", y_name) else "Gain (dB)"
            return x, self.db().y.magnitude, {"xlabel": "Frequency", "ylabel": ylabel, "xscale": xscale,
                                              "label": y_name}
        y = _engineering(self.y)
        xlabel = "Time" if self.x.check("[time]") else "Frequency" if self.is_frequency else (self.xname or "x")
        ylabel = ("Voltage" if self.y.check("[electric_potential]") else
                  "Current" if self.y.check("[current]") else
                  "Phase" if self.y.units == ureg.degree else y_name)
        return x, y, {"xlabel": xlabel, "ylabel": ylabel, "label": y_name, "xscale": xscale}

    def _sweep_axis(self):
        """A frequency sweep over decades is drawn on a log axis in Hz (decade ticks);
        a narrow one, or time, on a linear axis in a readable unit."""
        import numpy as np
        if self.is_frequency:
            positive = self._xm[self._xm > 0]
            if len(positive) and positive.max() / positive.min() >= 30:
                return self.x.to("Hz"), "log"
        return _engineering(self.x), "linear"

    def kip_content(self, kind: str):
        if kind == "plot":
            from .content import plot
            return plot(self)
        return self

    def kip_summary(self) -> str:
        return (f"signal {self.name}: {len(self)} points, {fmt_quantity(_engineering(self._xq(self._xm[0])))}"
                f" to {fmt_quantity(_engineering(self._xq(self._xm[-1])))}")


def _cross(x, y, i: int, level: float) -> float:
    """Where ``y`` passes ``level`` between points ``i`` and ``i + 1``, on a logarithmic
    ``x`` axis: a cubic through the neighbouring points, so a coarse sweep still
    gives the crossing to a fraction of a percent."""
    import numpy as np
    lo, hi = max(0, i - 1), min(len(x), i + 3)
    if x[lo] <= 0:
        return float(x[i])
    u = np.log10(np.asarray(x[lo:hi], dtype=float))
    v = np.asarray(y[lo:hi], dtype=float) - level
    if not np.all(np.isfinite(v)):
        return float(x[i])
    coeffs = np.polyfit(u - u[0], v, min(3, len(u) - 1))
    a, b = math.log10(x[i]) - u[0], math.log10(x[i + 1]) - u[0]
    fa = np.polyval(coeffs, a)
    if fa * np.polyval(coeffs, b) > 0:  # the fit does not bracket it: fall back to a straight line
        t = (level - y[i]) / (y[i + 1] - y[i]) if y[i + 1] != y[i] else 0.0
        return float(10 ** (math.log10(x[i]) + t * (math.log10(x[i + 1]) - math.log10(x[i]))))
    for _ in range(60):
        mid = (a + b) / 2
        if fa * np.polyval(coeffs, mid) <= 0:
            b = mid
        else:
            a, fa = mid, np.polyval(coeffs, mid)
    return float(10 ** ((a + b) / 2 + u[0]))

# -- standard values ---------------------------------------------------------------------

_E12 = (1.0, 1.2, 1.5, 1.8, 2.2, 2.7, 3.3, 3.9, 4.7, 5.6, 6.8, 8.2)
_E24 = (1.0, 1.1, 1.2, 1.3, 1.5, 1.6, 1.8, 2.0, 2.2, 2.4, 2.7, 3.0, 3.3, 3.6, 3.9, 4.3, 4.7, 5.1,
        5.6, 6.2, 6.8, 7.5, 8.2, 9.1)


def _computed(n: int) -> tuple[float, ...]:
    values = [round(10 ** (k / n), 2) for k in range(n)]
    return tuple(9.2 if n == 192 and v == 9.19 else v for v in values)


#: Preferred numbers (IEC 60063): the values resistors and capacitors are made in.
E_SERIES = {"E3": (1.0, 2.2, 4.7), "E6": (1.0, 1.5, 2.2, 3.3, 4.7, 6.8), "E12": _E12, "E24": _E24,
            "E48": _computed(48), "E96": _computed(96), "E192": _computed(192)}


def standard_value(value, series: str | int = "E24", *, round: str = "nearest"):
    """The preferred value (IEC 60063) nearest to ``value``, units kept.

    ``standard_value(15.9 * kohm, "E24")`` is 16 kΩ; the series may be given
    as its number, ``standard_value(R, 96)``, which a calc cell can write.
    ``round="up"`` or ``"down"`` takes the next one above or below instead.
    """
    try:
        steps = E_SERIES[f"E{series}" if isinstance(series, int) else series.upper()]
    except KeyError:
        raise ValueError(f"series is one of {', '.join(E_SERIES)}") from None
    if round not in ("nearest", "up", "down"):
        raise ValueError("round is 'nearest', 'up' or 'down'")
    q = value if isinstance(value, ureg.Quantity) else None
    unit = _base_unit(q) if q is not None else None
    x = float(q.to(unit).magnitude if q is not None else value)
    if x <= 0:
        raise ValueError("a standard value is positive")
    decade = math.floor(math.log10(x))
    candidates = [s * 10 ** d for d in (decade - 1, decade, decade + 1) for s in steps]
    if round == "up":
        best = min(c for c in candidates if c >= x * (1 - 1e-9))
    elif round == "down":
        best = max(c for c in candidates if c <= x * (1 + 1e-9))
    else:
        best = min(candidates, key=lambda c: abs(math.log(c / x)))
    best = float(f"{best:.4g}")
    if q is None:
        return best
    shown = ureg.Quantity(best, unit).to(q.units)
    return ureg.Quantity(float(f"{shown.magnitude:.6g}"), q.units)  # 10.7 kΩ, not 10.700000000000001


def _base_unit(q):
    for name in ("ohm", "farad", "henry", "volt", "ampere", "watt", "hertz", "second"):
        if q.check(ureg(name).dimensionality):
            return name
    return q.to_base_units().units
