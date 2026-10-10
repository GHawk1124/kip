"""Electronics: SPICE, schematics, boards, fabrication files, HDL, RF and chip layout."""
import math
import struct
import zipfile
from types import SimpleNamespace

import numpy as np
import pytest
from typer.testing import CliRunner

from kip import (Board, Schematic, cutoff, fmax, gain_at, microstrip, overshoot, phase_margin, pulse_width,
                 read_constraints, read_csx, read_drill, read_gds, read_gerbers, read_hdl, read_magic,
                 read_metrics, read_netlist, read_raw, read_schematic, read_timing, read_touchstone,
                 read_utilization, read_vcd, rise_time, simulate, smith_chart, polar_pattern, spice_value,
                 standard_value, stripline, trace_width, wavedrom)
from kip.cli import app
from kip.doc import build
from kip.schematic import KicadNetlist, XSchematic, from_skidl, reference_ranges
from kip.spice import E_SERIES, Netlist, Signal
from kip.units import fmt_quantity, ureg

CIRCUIT = "src/kip/assets/templates/circuit/input/"
FPGA = "src/kip/assets/templates/fpga/input/"
R, C = 1e3, 100e-9                     # the RC low-pass the synthetic files hold
F_C = 1 / (2 * math.pi * R * C)        # 1591.5 Hz
TAU = R * C


def q(text):
    return ureg.Quantity(text)


# -- SPICE values and netlists -------------------------------------------------------

def test_spice_values_read_suffixes_and_rkm_codes():
    assert spice_value("4k7") == pytest.approx(4700)
    assert spice_value("10Meg") == pytest.approx(10e6)
    assert spice_value("1M") == pytest.approx(1e-3)        # SPICE's M is milli
    assert spice_value("100nF") == pytest.approx(100e-9)   # the unit after the suffix is ignored
    assert spice_value("2R2") == pytest.approx(2.2)
    assert spice_value("1.5u") == pytest.approx(1.5e-6)


def test_a_netlist_reads_elements_nodes_and_analyses_and_takes_new_values():
    net = Netlist.parse("""* divider
V1 in 0 DC 5
R1 in out 4k7
R2 out 0 {Rb}
C1 out 0 100nF
.param Rb=10k
.op
.end
""")
    assert [e.name for e in net] == ["V1", "R1", "R2", "C1"]
    assert net["R1"].quantity == q("4.7 kohm") and fmt_quantity(net["C1"].quantity) == "100 nF"
    assert net["R2"].value is None and net["R2"].value_text == "{Rb}"
    assert set(net.nodes) == {"in", "out", "0"} and [a.text for a in net.analyses] == [".op"]
    changed = net.with_values(R1=2.2 * ureg.kohm, C1="47n")
    assert changed["R1"].value == pytest.approx(2200) and changed["C1"].value_text == "47n"
    assert net["R1"].value == pytest.approx(4700)  # the original is unchanged


def test_kicad_spice_export_reads_with_its_subcircuit_and_sheet_paths():
    net = read_netlist(CIRCUIT + "sallen_key.cir")
    assert {"/IN", "/OUT", "GND"} <= set(net.nodes)
    assert net["XU1"].model == "OPAMP" and net["XU1"].nodes[-1] == "/OUT"
    assert net["R1"].quantity == q("10.7 kohm")            # not 10.700000000000001
    assert "PULSE" in net["V1"].value_text and [a.text for a in net.analyses] == [".ac dec 50 10 100k", ".tran 5u 4m"]


def test_e_series_are_iec_60063_and_standard_value_rounds_in_the_unit_given():
    assert len(E_SERIES["E96"]) == 96 and E_SERIES["E96"][:4] == (1.0, 1.02, 1.05, 1.07)
    assert E_SERIES["E24"][-1] == 9.1 and E_SERIES["E12"][4] == 2.2
    assert standard_value(15.9 * ureg.kohm) == q("16 kohm")
    assert standard_value(10.73 * ureg.kohm, 96) == q("10.7 kohm")     # the series by number
    assert str(standard_value(10.73 * ureg.kohm, 96).magnitude) == "10.7"
    assert standard_value(12.3 * ureg.nF, "E12", round="up") == q("15 nF")
    assert standard_value(12.3 * ureg.nF, "E12", round="down") == q("12 nF")
    with pytest.raises(ValueError, match="series is one of"):
        standard_value(1.0, "E7")


# -- raw files and measurements ------------------------------------------------------

def _header(plotname, flags, variables, points, title="rc"):
    lines = [f"Title: {title}", "Date: today", f"Plotname: {plotname}", f"Flags: {flags}",
             f"No. Variables: {len(variables)}", f"No. Points: {points}", "Variables:"]
    lines += [f"\t{k}\t{name}\t{kind}" for k, (name, kind) in enumerate(variables)]
    return "\n".join(lines) + "\n"


def _ac_rows():
    f = np.logspace(1, 5, 401)
    return f, 1 / (1 + 1j * f / F_C)


def _tran_rows():
    t = np.linspace(0, 1e-3, 2001)
    return t, 1 - np.exp(-t / TAU)


def _ngspice_raw():
    """An AC sweep in ASCII and a transient in binary, one after the other, as ngspice -r writes."""
    f, h = _ac_rows()
    text = _header("AC Analysis", "complex", [("frequency", "frequency"), ("v(in)", "voltage"),
                                               ("v(out)", "voltage")], len(f)) + "Values:\n"
    for k, (fk, hk) in enumerate(zip(f, h)):
        text += f"{k}\t{fk:.17g},0.0\n\t1.0,0.0\n\t{hk.real:.17g},{hk.imag:.17g}\n"
    t, v = _tran_rows()
    binary = _header("Transient Analysis", "real", [("time", "time"), ("v(out)", "voltage")], len(t)) + "Binary:\n"
    return text.encode("latin-1") + binary.encode("latin-1") + np.column_stack([t, v]).astype("<f8").tobytes()


def test_an_ngspice_raw_file_reads_every_analysis_and_measures_them(tmp_path):
    path = tmp_path / "rc.raw"
    path.write_bytes(_ngspice_raw())
    results = read_raw(path)
    assert [a.kind for a in results] == ["ac", "tran"]
    H = results.ac.v("out") / results.ac.v("in")
    assert cutoff(H).to("Hz").magnitude == pytest.approx(F_C, rel=2e-3)
    assert gain_at(H, 10 * F_C * ureg.Hz) == pytest.approx(-20 * math.log10(math.hypot(1, 10)), abs=0.05)
    v = results.tran.v("out")
    assert rise_time(v).to("us").magnitude == pytest.approx(TAU * math.log(9) * 1e6, rel=5e-3)
    assert overshoot(v).magnitude == pytest.approx(0, abs=1e-6)
    assert v.final.magnitude == pytest.approx(1 - math.exp(-10), rel=1e-6)


def test_ltspice_binary_and_text_exports_read_like_ngspice(tmp_path):
    t, v = _tran_rows()
    head = _header("Transient Analysis", "real forward", [("time", "time"), ("V(out)", "voltage")], len(t),
                   title="* rc.asc").replace("Variables:\n", "Offset: 0.0\nCommand: LTspice\nVariables:\n")
    stamps = t.copy()
    stamps[5] = -stamps[5]  # LTspice marks compressed points with a negative time
    rec = np.zeros(len(t), dtype=[("x", "<f8"), ("v", "<f4")])
    rec["x"], rec["v"] = stamps, v
    (tmp_path / "rc.raw").write_bytes((head + "Binary:\n").encode("utf-16-le") + rec.tobytes())
    tran = read_raw(tmp_path / "rc.raw").tran
    assert tran.time[5].magnitude == pytest.approx(t[5])
    assert rise_time(tran.v("out")).to("us").magnitude == pytest.approx(TAU * math.log(9) * 1e6, rel=5e-3)

    f, h = _ac_rows()
    lines = ["Freq.\tV(out)"] + [f"{fk:.15e}\t({20 * math.log10(abs(hk)):.6e}dB,{math.degrees(np.angle(hk)):.6e}°)"
                                 for fk, hk in zip(f, h)]
    (tmp_path / "rc.txt").write_text("\n".join(lines), encoding="utf-8")
    ac = read_raw(tmp_path / "rc.txt").ac
    assert cutoff(ac.v("out")).to("Hz").magnitude == pytest.approx(F_C, rel=2e-3)


def test_a_kicad_sheet_path_node_is_found_by_its_short_name():
    results = read_raw(CIRCUIT + "sallen_key.raw")
    assert cutoff(results.ac.v("out")) == cutoff(results.ac.v("/out"))
    difference = results.tran.v("out", "in")   # one node against another
    assert difference.initial.magnitude == pytest.approx(0, abs=1e-6)


def test_phase_margin_of_a_two_pole_loop():
    f = np.logspace(2, 7, 2001)
    wp = 2 * math.pi * 1e4
    s = 2j * math.pi * f
    T = math.sqrt(2) * wp / (s * (1 + s / wp))  # crosses 0 dB at the second pole: 45°
    loop = Signal(ureg.Quantity(f, "Hz"), ureg.Quantity(T, "dimensionless"), name="T", xname="frequency")
    assert phase_margin(loop).to("degree").magnitude == pytest.approx(45, abs=0.2)


def test_simulate_reuses_its_cache_and_says_what_to_install_without_one(tmp_path, monkeypatch):
    import kip.spice
    net = read_netlist(CIRCUIT + "sallen_key.cir")
    designed = net.with_values(R1=10.7 * ureg.kohm, R2=10.7 * ureg.kohm, C1=22 * ureg.nF, C2=10 * ureg.nF)
    monkeypatch.setattr(kip.spice, "_ngspice", lambda: None)
    results = simulate(designed, cache=CIRCUIT + "sallen_key.raw")   # the template's own cache
    assert cutoff(results.ac.v("out")).to("kHz").magnitude == pytest.approx(1.049, abs=0.002)
    with pytest.raises(RuntimeError, match="needs ngspice.*cached results are for a different netlist"):
        simulate(designed.with_values(R1=12 * ureg.kohm), cache=CIRCUIT + "sallen_key.raw")
    with pytest.raises(RuntimeError, match="nothing is cached"):
        simulate(designed, cache=tmp_path / "none.raw")


@pytest.mark.skipif(__import__("kip.spice", fromlist=["_ngspice"])._ngspice() is None, reason="ngspice not installed")
def test_simulate_runs_ngspice_and_writes_a_cache_it_then_reads(tmp_path):
    netlist = f"""* rc
V1 in 0 DC 0 AC 1
R1 in out {R:g}
C1 out 0 {C:g}
.ac dec 100 10 100k
.end
"""
    first = simulate(netlist, cache=tmp_path / "rc.raw")
    assert cutoff(first.ac.v("out")).to("Hz").magnitude == pytest.approx(F_C, rel=5e-3)
    assert (tmp_path / "rc.raw").exists()
    again = read_raw(tmp_path / "rc.raw")
    assert "kip-" in again.title


# -- schematics -----------------------------------------------------------------------

def test_a_kicad_schematic_lists_its_parts_and_draws_with_its_file_attached():
    sch = Schematic.load(CIRCUIT + "sallen_key.kicad_sch")
    assert sch.title == "Sallen-Key low-pass filter"
    assert sorted(p.reference for p in sch.parts) == ["C1", "C2", "C3", "C4", "J1", "R1", "R2", "U1"]
    bom = sch.bom()
    assert ("R1, R2", 2, "10.7k", "R_0805_2012Metric") in bom.rows
    assert ("C3, C4", 2, "100n", "C_0805_2012Metric") in bom.rows
    drawing = sch.drawing()
    assert b"<svg" in drawing.svg and "sallen_key.kicad_sch" in drawing.attachments
    assert read_schematic(CIRCUIT + "sallen_key.kicad_sch").title == sch.title


def test_reference_ranges_collapse_runs_of_three_or_more():
    assert reference_ranges(["R5", "R1", "R2", "R3", "C1", "C2"]) == "C1, C2, R1–R3, R5"


def test_an_xschem_schematic_draws_known_symbols_from_stand_ins_and_boxes_the_rest(tmp_path, monkeypatch):
    monkeypatch.delenv("XSCHEM_LIBRARY_PATH", raising=False)
    monkeypatch.delenv("PDK_ROOT", raising=False)
    (tmp_path / "rc.sch").write_text("""v {xschem version=3.4.5 file_version=1.2}
G {}
N 0 -60 0 -30 {lab=out}
C {devices/res.sym} 0 -90 0 0 {name=R1 value=1k}
C {devices/capa.sym} 0 0 0 0 {name=C1 value=100n}
C {devices/lab_pin.sym} 0 -60 0 0 {name=p1 lab=out}
C {mylib/widget.sym} 100 0 0 0 {name=X1}
""", encoding="utf-8")
    sch = XSchematic.load(tmp_path / "rc.sch")
    assert [c["name"] for c in sch.parts] == ["R1", "C1", "X1"]
    assert ("R1", "res", "1k") in sch.table().rows
    drawing = sch.drawing()
    assert b"<svg" in drawing.svg
    assert "devices/res.sym" in sch.standins and sch.missing == ["mylib/widget.sym"]


NETLIST = """(export (version "E")
  (components
    (comp (ref "R1") (value "10k") (footprint "Resistor_SMD:R_0805_2012Metric")
      (property (name "Tolerance") (value "1%")))
    (comp (ref "R2") (value "10k") (footprint "Resistor_SMD:R_0805_2012Metric"))
    (comp (ref "C1") (value "100n") (footprint "Capacitor_SMD:C_0805_2012Metric")))
  (nets
    (net (code "1") (name "/IN") (node (ref "R1") (pin "1")))
    (net (code "2") (name "/MID") (node (ref "R1") (pin "2")) (node (ref "R2") (pin "1"))
      (node (ref "C1") (pin "1") (pinfunction "A")))
    (net (code "3") (name "GND") (node (ref "R2") (pin "2")) (node (ref "C1") (pin "2")))))
"""


def test_a_kicad_netlist_gives_parts_nets_and_connections():
    net = KicadNetlist.parse(NETLIST, name="divider")
    assert net["R1"]["Tolerance"] == "1%" and net["C1"]["value"] == "100n"
    assert net.net("MID") == [("R1", "2", ""), ("R2", "1", ""), ("C1", "1", "A")]
    assert net.connections("R2") == {"1": "/MID", "2": "GND"}
    rows = net.nets_table().rows
    assert ("MID", 3, "C1.1, R1.2, R2.1") in rows
    assert net.kip_summary() == "netlist divider: 3 parts, 3 nets"
    with pytest.raises(ValueError, match="not a KiCad netlist"):
        KicadNetlist.parse("(kicad_sch)")


def test_a_skidl_circuit_reads_as_a_netlist_without_writing_files():
    def pin(part, num, name=""):
        return SimpleNamespace(part=part, num=num, name=name)
    r1 = SimpleNamespace(ref="R1", value="1k", footprint="R_0805", fields={"MPN": "RC0805"})
    c1 = SimpleNamespace(ref="C1", value="100n", footprint="C_0805")
    circuit = SimpleNamespace(name="rc", parts=[r1, c1], get_nets=lambda: [
        SimpleNamespace(name="out", get_pins=lambda: [pin(r1, 2), pin(c1, 1)]),
        SimpleNamespace(name="NC", get_pins=lambda: [])])
    net = from_skidl(circuit)
    assert net["R1"]["MPN"] == "RC0805" and net.nets == {"out": [("R1", "2", ""), ("C1", "1", "")]}


def test_a_skidl_circuit_in_a_table_cell_is_its_bill_of_materials(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # SKiDL writes its logs to the working directory
    skidl = pytest.importorskip("skidl")
    from kip.adapters import adapt
    two = [skidl.Pin(num=1, func=skidl.Pin.types.PASSIVE), skidl.Pin(num=2, func=skidl.Pin.types.PASSIVE)]
    R = skidl.Part(tool=skidl.SKIDL, name="R", ref_prefix="R", dest=skidl.TEMPLATE, pins=[p.copy() for p in two])
    Cap = skidl.Part(tool=skidl.SKIDL, name="C", ref_prefix="C", dest=skidl.TEMPLATE, pins=[p.copy() for p in two])
    rc = skidl.Circuit(name="rc")
    with rc:
        r1, c1 = R(value="1k", footprint="R_0805"), Cap(value="100n", footprint="C_0805")
        vin, out, gnd = skidl.Net("IN"), skidl.Net("OUT"), skidl.Net("GND")
        vin += r1[1]
        out += r1[2], c1[1]
        gnd += c1[2]
    assert sorted(from_skidl(rc).nets["OUT"]) == [("C1", "1", ""), ("R1", "2", "")]
    assert adapt(rc, "table").rows == [("C1", 1, "100n", "C_0805"), ("R1", 1, "1k", "R_0805")]


def test_a_schemdraw_drawing_is_vector_with_kips_fonts():
    schemdraw = pytest.importorskip("schemdraw")
    import schemdraw.elements as elm
    from kip.adapters import adapt
    with schemdraw.Drawing(show=False) as d:
        elm.Resistor().label("R1")
        elm.Capacitor().down().label("C1")
    drawing = adapt(d, "draw")
    assert b"<svg" in drawing.svg and drawing.width > 10
    assert b"R1" in drawing.svg or b"<path" in drawing.svg


# -- boards and fabrication files -----------------------------------------------------

def test_a_board_reports_its_size_layers_tracks_and_holes():
    board = Board.load(CIRCUIT + "sallen_key.kicad_pcb")
    assert board.size == (q("46 mm"), q("26 mm")) and board.copper_layers == ["F.Cu", "B.Cu"]
    assert board.min_track == q("0.25 mm") and max(board.track_widths) == q("0.5 mm")
    assert len(board.holes) == 17 and board.min_drill == q("0.4 mm")
    assert board.drill_table().rows == [("0.4", "plated", 10), ("1", "plated", 5), ("3.2", "non-plated", 2)]
    assert board.track_length("/OUT") == board.track_length("OUT") > q("90 mm")   # KiCad 10 names nets
    assert ("Pads", "20 SMD, 7 through-hole") in board.summary_table().rows
    with pytest.raises(KeyError, match="no net"):
        board.track_length("NOPE")


def test_a_board_draws_at_the_width_asked_for_and_by_layer():
    board = Board.load(CIRCUIT + "sallen_key.kicad_pcb")
    top, copper = board.drawing(), board.drawing(view="copper")
    assert top.width == 120 and copper.width == 120   # enlarged from 46 mm
    assert b"<svg" in copper.svg and copper.svg != top.svg


def test_gerbers_and_drills_read_back_match_the_board(tmp_path):
    board = Board.load(CIRCUIT + "sallen_key.kicad_pcb")
    fab = read_gerbers(CIRCUIT + "fab.zip")
    assert fab.size == board.size and fab.copper_layers == 2
    assert fab.drill_table().rows == board.drill_table().rows and fab.min_drill == board.min_drill
    roles = {role for _, role, _ in fab.layer_table().rows}
    assert {"copper (top)", "copper (bottom)", "outline", "drill"} <= roles
    with zipfile.ZipFile(CIRCUIT + "fab.zip") as z:
        z.extract("sallen_key.drl", tmp_path)
    drill = read_drill(tmp_path / "sallen_key.drl")
    assert drill.min_diameter == q("0.4 mm") and len(drill.holes) == 17
    assert fab.drawing().width == 120


def test_ipc_2221_trace_width_and_line_impedances():
    supply = trace_width(I=2 * ureg.A, dT=10 * ureg.K, t=35 * ureg.um)
    assert supply.w.to("mm").magnitude == pytest.approx(0.781, abs=0.002)
    inner = trace_width(I=2 * ureg.A, dT=10 * ureg.K, t=35 * ureg.um, external=False)
    assert inner.w > supply.w
    line = microstrip(w=3 * ureg.mm, h=1.6 * ureg.mm, t=35 * ureg.um, e_r=4.3)
    assert line.Z_0.to("ohm").magnitude == pytest.approx(50.5, abs=0.5)
    buried = stripline(w=0.5 * ureg.mm, b=1.6 * ureg.mm, t=35 * ureg.um, e_r=4.3)
    assert 40 < buried.Z_0.to("ohm").magnitude < 60
    assert ureg.Quantity(1, "mil").to("mm").magnitude == pytest.approx(0.0254)


# -- HDL, waveforms and FPGA reports --------------------------------------------------

def test_a_verilog_module_reads_its_parameters_ports_and_comments():
    uart = read_hdl(FPGA + "uart_tx.v")["uart_tx"]
    assert uart.parameters == {"CLK_HZ": "12_000_000", "BAUD": "115_200"}
    assert uart.parameter("CLK_HZ") == 12_000_000 and uart.parameter("baud") == 115_200
    assert [(p.name, p.direction, p.width) for p in uart.ports] == [
        ("clk", "in", 1), ("rst_n", "in", 1), ("data", "in", 8), ("valid", "in", 1), ("ready", "out", 1),
        ("tx", "out", 1)]
    assert uart["data"].description == "byte to send, held while valid" and uart.io_bits == 13
    symbol = uart.symbol()
    assert b"uart_tx" in symbol.svg and b"CLK_HZ" in symbol.svg
    with pytest.raises(KeyError, match="no parameter 'DEPTH'; there are CLK_HZ, BAUD"):
        uart.parameter("DEPTH")


def test_systemverilog_widths_follow_parameters(tmp_path):
    (tmp_path / "mul.sv").write_text("""module mul #(parameter int W = 16) (
    input  logic           clk,   // clock
    input  logic [W-1:0]   a,     // operand
    output logic [2*W-1:0] p      // product
);
endmodule
""", encoding="utf-8")
    mul = read_hdl(tmp_path / "mul.sv")[0]
    assert [(p.name, p.width) for p in mul.ports] == [("clk", 1), ("a", 16), ("p", 32)]
    assert mul["p"].description == "product"


def test_a_vhdl_entity_reads_generics_and_port_widths(tmp_path):
    (tmp_path / "counter.vhd").write_text("""library ieee;
use ieee.std_logic_1164.all;
entity counter is
  generic (WIDTH : natural := 12);
  port (
    clk   : in  std_logic;                            -- the clock
    count : out std_logic_vector(WIDTH-1 downto 0);   -- the count
    level : in  integer range 0 to 255
  );
end entity counter;
""", encoding="utf-8")
    counter = read_hdl(tmp_path / "counter.vhd")["counter"]
    assert counter.language == "vhdl" and counter.parameter("WIDTH") == 12
    assert [(p.name, p.direction, p.width) for p in counter.ports] == [
        ("clk", "in", 1), ("count", "out", 12), ("level", "in", 8)]
    assert counter["clk"].description == "the clock"


def test_a_vcd_measures_its_signals():
    sim = read_vcd(FPGA + "uart_tx.vcd")
    assert sim.unit == "us" and sim.duration.to("us").magnitude == pytest.approx(90, abs=1)
    tx = sim["tx"]
    assert tx.name == "tb.tx" and sim["tb.tx"] is tx and "nope" not in sim
    assert pulse_width(tx, 0).to("us").magnitude == pytest.approx(104 / 12, rel=1e-3)   # the start bit
    assert sim["clk"].frequency().to("MHz").magnitude == pytest.approx(12, rel=1e-4)
    assert sim["data"].int_at(0) == 0x4B and sim["busy"].pulse("1").to("us").magnitude == pytest.approx(86.67, abs=0.01)
    diagram = sim.timing("valid", "tx", "bit_index", end=92 * ureg.us)
    assert b"bit_index" in diagram.svg
    with pytest.raises(ValueError, match="end after start"):
        sim.timing("tx", start=5 * ureg.us, end=5 * ureg.us)


def test_a_vcd_finds_the_shallowest_signal_of_a_name_and_reads_reals(tmp_path):
    (tmp_path / "t.vcd").write_text("""$timescale 1ns $end
$scope module top $end
$var wire 1 ! clk $end
$scope module u $end
$var wire 1 # clk $end
$var real 64 " level $end
$upscope $end
$upscope $end
$enddefinitions $end
#0
0!
0#
r0.5 "
#5
1!
1#
#10
0!
0#
r1.25 "
#15
1!
1#
#20
0!
0#
""", encoding="utf-8")
    trace = read_vcd(tmp_path / "t.vcd")
    assert trace["clk"].name == "top.clk" and trace["u.clk"].name == "top.u.clk"
    assert trace["level"].value_at(12 * ureg.ns) == "1.25"
    assert trace["clk"].period().to("ns").magnitude == pytest.approx(10)


def test_wavedrom_draws_clocks_data_and_groups_from_json5():
    drawing = wavedrom("""{signal: [
      {name: 'clk', wave: 'p.....'},
      ['bus', {name: 'data', wave: 'x.34x.', data: ['head', 'body']}],
    ]}""")
    assert b"head" in drawing.svg and b"body" in drawing.svg and b"bus" in drawing.svg
    with pytest.raises(ValueError, match="no signal with a wave"):
        wavedrom({"signal": [{"name": "x"}]})


VIVADO_UTIL = """Utilization Design Information

1. Slice Logic
--------------

+-------------------------+------+-------+------------+-----------+-------+
|        Site Type        | Used | Fixed | Prohibited | Available | Util% |
+-------------------------+------+-------+------------+-----------+-------+
| Slice LUTs              |  120 |     0 |          0 |     20800 |  0.58 |
|   LUT as Logic          |  120 |     0 |          0 |     20800 |  0.58 |
| Slice Registers         |   85 |     0 |          0 |     41600 |  0.20 |
+-------------------------+------+-------+------------+-----------+-------+
"""

YOSYS_OLD = """=== top ===

   Number of wires:                 42
   Number of cells:                 58
     SB_LUT4                        30
     SB_DFFESR                      11
"""


def test_utilization_from_yosys_nextpnr_and_vivado(tmp_path):
    synthesis = read_utilization(FPGA + "stat.json")
    assert synthesis.tool == "yosys" and synthesis["SB_LUT4"] == 30
    assert [c.title for c in synthesis.table().columns] == ["Resource", "Used"]   # nothing to fill
    placed = read_utilization(FPGA + "report.json")
    assert placed["ICESTORM_LC"] == 42 and placed.available("ICESTORM_LC") == 5280
    assert placed.percent("SB_IO").magnitude == pytest.approx(100 * 13 / 39)
    assert ("Logic cells", 42, 5280, "0.8") in placed.table(titles={"ICESTORM_LC": "Logic cells"}).rows
    (tmp_path / "util.rpt").write_text(VIVADO_UTIL, encoding="utf-8")
    vivado = read_utilization(tmp_path / "util.rpt")
    assert vivado.rows == [("Slice LUTs", 120, 20800), ("Slice Registers", 85, 41600)]
    (tmp_path / "stat.txt").write_text(YOSYS_OLD, encoding="utf-8")
    old = read_utilization(tmp_path / "stat.txt")
    assert old["cells"] == 58 and old["SB_DFFESR"] == 11
    (tmp_path / "stat_new.txt").write_text("=== uart_tx ===\n\n       58 cells\n       30   SB_LUT4\n"
                                           "       42 wires\n", encoding="utf-8")
    new = read_utilization(tmp_path / "stat_new.txt")
    assert new["cells"] == 58 and new["SB_LUT4"] == 30 and "wires" not in [r[0] for r in new.rows]


VIVADO_TIMING = """------------------------------------------------------------------------------------------------
| Design Timing Summary
| ---------------------
------------------------------------------------------------------------------------------------

    WNS(ns)      TNS(ns)  TNS Failing Endpoints  TNS Total Endpoints      WHS(ns)      THS(ns)  THS Failing Endpoints  THS Total Endpoints
    -------      -------  ---------------------  -------------------      -------      -------  ---------------------  -------------------
      2.345        0.000                      0                  210        0.112        0.000                      0                  210


------------------------------------------------------------------------------------------------
| Clock Summary
| -------------
------------------------------------------------------------------------------------------------

Clock        Waveform(ns)       Period(ns)      Frequency(MHz)
-----        ------------       ----------      --------------
sys_clk_pin  {0.000 5.000}      10.000          100.000

"""


def test_timing_from_nextpnr_vivado_and_opensta(tmp_path):
    report = read_timing(FPGA + "report.json")
    assert report.met and fmax(report).to("MHz").magnitude == pytest.approx(79.80, abs=0.01)
    assert list(report.clocks) == ["clk"]     # nextpnr's buffer suffix is dropped
    (tmp_path / "nextpnr.log").write_text(
        "Info: Max frequency for clock 'clk$SB_IO_IN_$glb_clk': 84.43 MHz (PASS at 12.00 MHz)\n"
        "Info: Max frequency for clock 'clk$SB_IO_IN_$glb_clk': 79.80 MHz (PASS at 12.00 MHz)\n", encoding="utf-8")
    assert read_timing(tmp_path / "nextpnr.log").fmax("clk").magnitude == pytest.approx(79.80)  # after routing
    (tmp_path / "timing.rpt").write_text(VIVADO_TIMING, encoding="utf-8")
    vivado = read_timing(tmp_path / "timing.rpt")
    assert vivado.wns == q("2.345 ns") and vivado.whs == q("0.112 ns") and vivado.met
    assert vivado.fmax().magnitude == pytest.approx(1000 / (10 - 2.345))
    (tmp_path / "sta.rpt").write_text("wns -0.12\ntns -1.50\nclk period_min = 10.12 fmax = 98.81\n",
                                      encoding="utf-8")
    sta = read_timing(tmp_path / "sta.rpt")
    assert not sta.met and sta.fmax("clk").magnitude == pytest.approx(98.81)
    assert sta.table().highlight == {0: "fail", 1: "fail"}


def test_pin_constraints_in_every_vendors_format(tmp_path):
    pcf = read_constraints(FPGA + "pins.pcf")
    assert pcf.pin("clk") == "35" and len(pcf.pins) == 13
    assert [r[0] for r in pcf.table().rows][:3] == ["clk", "data[0]", "data[1]"]   # in natural order
    files = {
        "top.xdc": """## Clock
set_property -dict { PACKAGE_PIN E3 IOSTANDARD LVCMOS33 } [get_ports { CLK100MHZ }];
create_clock -add -name sys_clk_pin -period 10.00 -waveform {0 5} [get_ports { CLK100MHZ }];
set_property PACKAGE_PIN D10 [get_ports uart_txd]
set_property IOSTANDARD LVCMOS33 [get_ports uart_txd]
""",
        "top.lpf": 'LOCATE COMP "clk" SITE "G2";\nIOBUF PORT "clk" IO_TYPE=LVCMOS33;\nFREQUENCY PORT "clk" 25 MHZ;\n',
        "top.qsf": 'set_location_assignment PIN_R8 -to CLOCK_50\n'
                   'set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to CLOCK_50\n',
        "top.cst": 'IO_LOC "clk" 52;\nIO_PORT "clk" IO_TYPE=LVCMOS33 PULL_MODE=UP;\n',
    }
    for name, text in files.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    xdc = read_constraints(tmp_path / "top.xdc")
    assert xdc.pin("CLK100MHZ") == "E3" and xdc.pins[1] == {"port": "uart_txd", "pin": "D10", "standard": "LVCMOS33"}
    assert xdc.clocks == [{"name": "sys_clk_pin", "port": "CLK100MHZ", "period": 10.0}]
    lpf = read_constraints(tmp_path / "top.lpf")
    assert lpf.pins == [{"port": "clk", "pin": "G2", "standard": "LVCMOS33"}] and lpf.clocks[0]["period"] == 40.0
    assert read_constraints(tmp_path / "top.qsf").pins == [{"port": "CLOCK_50", "pin": "R8", "standard": "3.3-V LVTTL"}]
    assert read_constraints(tmp_path / "top.cst").pins == [
        {"port": "clk", "pin": "52", "standard": "LVCMOS33", "extra": "PULL_MODE=UP"}]


# -- RF -------------------------------------------------------------------------------

def _series_rlc(f, L=100e-9, f0=1e9, z0=50.0):
    """A series RLC load, matched (50 Ω) at its resonance f0."""
    Cap = 1 / ((2 * math.pi * f0) ** 2 * L)
    z = z0 + 1j * (2 * math.pi * f * L - 1 / (2 * math.pi * f * Cap))
    return (z - z0) / (z + z0)


def test_a_one_port_touchstone_file_gives_match_and_bandwidth(tmp_path):
    f = np.linspace(0.8e9, 1.2e9, 2001)
    g = _series_rlc(f)
    lines = ["! a series RLC", "# MHz S MA R 50"]
    lines += [f"{fk / 1e6:.6f} {abs(gk):.9f} {math.degrees(np.angle(gk)):.6f}" for fk, gk in zip(f, g)]
    (tmp_path / "load.s1p").write_text("\n".join(lines), encoding="utf-8")
    net = read_touchstone(tmp_path / "load.s1p")
    assert net.ports == 1 and len(net) == 2001
    assert net.resonance().to("GHz").magnitude == pytest.approx(1.0, abs=1e-4)
    # |Γ| < -10 dB while |X| < Z0·2/3 ... the band is X_max / (2πL) wide: 53.05 MHz
    assert net.bandwidth().to("MHz").magnitude == pytest.approx(100 / 3 / (2 * math.pi * 100e-9) / 1e6, rel=2e-3)
    assert net.impedance().y.magnitude[1000].real == pytest.approx(50, abs=0.01)
    assert b"<svg" in smith_chart(net.s11).svg and b"<svg" in net.smith().svg


def test_two_port_data_order_in_touchstone_1_and_2(tmp_path):
    f = [1.0, 2.0]
    row = "{f} -40 0 -3 90 -20 45 -40 0"        # S11 S21 S12 S22 in version 1
    (tmp_path / "amp.s2p").write_text("# GHz S DB R 50\n" + "\n".join(row.format(f=v) for v in f),
                                      encoding="utf-8")
    v1 = read_touchstone(tmp_path / "amp.s2p")
    (tmp_path / "amp2.s2p").write_text(
        "[Version] 2.0\n# GHz S DB R 50\n[Number of Ports] 2\n[Two-Port Data Order] 12_21\n"
        "[Number of Frequencies] 2\n[Network Data]\n"
        + "\n".join(f"{v} -40 0 -20 45 -3 90 -40 0" for v in f) + "\n[End]\n", encoding="utf-8")
    v2 = read_touchstone(tmp_path / "amp2.s2p")
    for net in (v1, v2):
        assert net.s21.db().y.magnitude[0] == pytest.approx(-3)
        assert net.s12.db().y.magnitude[0] == pytest.approx(-20)
    assert np.allclose(v1.s, v2.s)


def test_a_polar_pattern_draws():
    theta = np.arange(0, 360, 5)
    gain = 6 * np.cos(np.radians(theta)) ** 2
    assert b"<svg" in polar_pattern(theta, gain, labels=["E-plane"]).svg


CSX = """<?xml version="1.0"?>
<openEMS>
  <FDTD NumberOfTimesteps="10000" endCriteria="1e-5" f_max="3e9">
    <Excitation Type="0" f0="1.5e9" fc="1.5e9"/>
    <BoundaryCond xmin="MUR" xmax="MUR" ymin="MUR" ymax="MUR" zmin="PEC" zmax="MUR"/>
  </FDTD>
  <ContinuousStructure CoordSystem="0">
    <Properties>
      <Material Name="FR4">
        <Property Epsilon="4.3" Kappa="0.001"/>
        <Primitives>
          <Box Priority="0"><P1 X="-25" Y="-20" Z="0"/><P2 X="25" Y="20" Z="1.6"/></Box>
        </Primitives>
      </Material>
      <Metal Name="patch">
        <Primitives>
          <Box Priority="10"><P1 X="-15" Y="-11" Z="1.6"/><P2 X="15" Y="11" Z="1.6"/></Box>
        </Primitives>
      </Metal>
    </Properties>
    <RectilinearGrid DeltaUnit="0.001" CoordSystem="0">
      <XLines>-50,-25,0,25,50</XLines>
      <YLines>-40,-20,0,20,40</YLines>
      <ZLines>0,0.8,1.6,30</ZLines>
    </RectilinearGrid>
  </ContinuousStructure>
</openEMS>
"""


def test_an_openems_model_reads_its_domain_mesh_and_materials(tmp_path):
    (tmp_path / "patch.xml").write_text(CSX, encoding="utf-8")
    geo = read_csx(tmp_path / "patch.xml")
    assert geo.size == (q("100 mm"), q("80 mm"), q("30 mm")) and geo.cells == 48
    assert geo.smallest_cell == q("0.8 mm") and geo.boundaries["zmin"] == "PEC"
    assert geo.materials_table().rows == [("FR4", "Material", "4.3", "0.001", 1), ("patch", "Metal", "–", "–", 1)]
    assert geo["patch"].primitives[0].bounds() == ((-15, -11, 1.6), (15, 11, 1.6))
    assert b"<svg" in geo.drawing().svg and b"<svg" in geo.drawing(plane="xz", mesh=True).svg


# -- chip layout ----------------------------------------------------------------------

def _real8(x):
    if x == 0:
        return bytes(8)
    exponent, x = 64, abs(x)
    while x >= 1:
        x, exponent = x / 16, exponent + 1
    while x < 1 / 16:
        x, exponent = x * 16, exponent - 1
    return bytes([exponent]) + int(round(x * (1 << 56))).to_bytes(7, "big")


def _gds():
    def rec(rtype, dtype, payload=b""):
        return struct.pack(">HBB", 4 + len(payload), rtype, dtype) + payload

    def name(text):
        raw = text.encode() + (b"\0" if len(text) % 2 else b"")
        return raw

    def xy(*points):
        return rec(0x10, 0x03, b"".join(struct.pack(">ii", x, y) for x, y in points))

    def box(layer, dt, x0, y0, x1, y1):
        return (rec(0x08, 0x00) + rec(0x0D, 0x02, struct.pack(">h", layer)) + rec(0x0E, 0x02, struct.pack(">h", dt))
                + xy((x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)) + rec(0x11, 0x00))

    stamp = struct.pack(">12h", *([2026, 1, 1, 0, 0, 0] * 2))
    data = rec(0x00, 0x02, struct.pack(">h", 600)) + rec(0x01, 0x02, stamp) + rec(0x02, 0x06, name("LIB"))
    data += rec(0x03, 0x05, _real8(1e-3) + _real8(1e-9))                     # 1 nm database unit
    data += rec(0x05, 0x02, stamp) + rec(0x06, 0x06, name("via")) + box(68, 20, 0, 0, 500, 500) + rec(0x07, 0x00)
    data += rec(0x05, 0x02, stamp) + rec(0x06, 0x06, name("top")) + box(67, 20, 0, 0, 2000, 1000)
    data += rec(0x0A, 0x00) + rec(0x12, 0x06, name("via")) + xy((3000, 0)) + rec(0x11, 0x00)
    data += (rec(0x0B, 0x00) + rec(0x12, 0x06, name("via")) + rec(0x13, 0x02, struct.pack(">hh", 2, 1))
             + xy((0, 2000), (2000, 2000), (0, 3000)) + rec(0x11, 0x00))
    data += (rec(0x09, 0x00) + rec(0x0D, 0x02, struct.pack(">h", 68)) + rec(0x0E, 0x02, struct.pack(">h", 20))
             + rec(0x0F, 0x03, struct.pack(">i", 200)) + xy((0, 500), (2000, 500)) + rec(0x11, 0x00))
    data += (rec(0x0C, 0x00) + rec(0x0D, 0x02, struct.pack(">h", 68)) + rec(0x16, 0x02, struct.pack(">h", 5))
             + xy((100, 100)) + rec(0x19, 0x06, name("VDD")) + rec(0x11, 0x00))
    return data + rec(0x07, 0x00) + rec(0x04, 0x00)


def test_a_gds_file_flattens_references_and_arrays(tmp_path):
    (tmp_path / "top.gds").write_bytes(_gds())
    layout = read_gds(tmp_path / "top.gds")
    assert layout.top.name == "top" and layout.top_cells == ["top"]
    assert layout.size == (q("3.5 um"), q("2.5 um"))           # the array's second via reaches 1.5 µm up
    assert len(layout.flatten()) == 1 + 1 + 2 + 1                # box, reference, two-wide array, path
    assert layout.layers == [(67, 20), (68, 20)] and layout.layer_name((68, 20)) == "met1"
    assert b"<svg" in layout.drawing(layers=["met1"]).svg
    with pytest.raises(KeyError, match="no layer 'met9'"):
        layout.drawing(layers=["met9"])
    import gzip
    (tmp_path / "top.gds.gz").write_bytes(gzip.compress(_gds()))
    assert read_gds(tmp_path / "top.gds.gz").size == layout.size


def test_a_magic_layout_reads_its_subcells_and_boxes_the_missing_ones(tmp_path):
    (tmp_path / "top.mag").write_text("""magic
tech sky130A
magscale 1 2
timestamp 0
<< nwell >>
rect 0 0 400 200
<< metal1 >>
rect 10 10 100 50
<< labels >>
rlabel metal1 10 10 100 50 0 VDD
use inv inv_0
timestamp 0
transform 1 0 200 0 1 0
box 0 0 100 100
use missing missing_0
timestamp 0
transform 1 0 0 0 1 300
box 0 0 50 50
<< end >>
""", encoding="utf-8")
    (tmp_path / "inv.mag").write_text("magic\ntech sky130A\n<< metal1 >>\nrect 0 0 100 100\n<< end >>\n",
                                      encoding="utf-8")
    layout = read_magic(tmp_path / "top.mag")
    assert set(layout.cells) == {"top", "inv", "missing"} and layout.source == "Magic"
    assert layout.size == (q("2 um"), q("1.75 um"))     # sky130: λ = 10 nm, magscale halves it
    assert layout.cells["missing"].polygons[0][0] == "subcell"
    assert b"<svg" in layout.drawing().svg


def test_openlane_metrics_from_json_and_csv(tmp_path):
    (tmp_path / "metrics.json").write_text('{"metrics": {"design__instance__count": 1234, '
                                           '"timing__setup__ws": 1.5, "route__drc_errors": 0}}', encoding="utf-8")
    m = read_metrics(tmp_path / "metrics.json")
    assert m.design__instance__count == 1234 and m.find("timing") == {"timing__setup__ws": 1.5}
    assert ("Cells", 1234) in m.table().rows
    (tmp_path / "metrics.csv").write_text("design,synth_cell_count,wire_length\nspm,420,1.5e3\n", encoding="utf-8")
    old = read_metrics(tmp_path / "metrics.csv")
    assert old["synth_cell_count"] == 420 and old["wire_length"] == 1500.0


# -- calc cells -----------------------------------------------------------------------

def test_a_calc_cell_renders_and_counts_the_lines_beside_a_calculation():
    doc = build(source='''from kip import *
# %% calc tracks "Tracks"
supply = trace_width(I=2 * A, dT=10 * K, t=35 * um)
w_2 = 2 * supply.w   # -> mm
assert supply.w <= 1 * mm, "Narrow enough"
''', path="doc.py")
    res = doc.results["tracks"]
    assert [c.passed for c in res.assertions] == [True] and res.assertions[0].line == 5
    rows = [e.wide() for e in res.equations]
    assert any("A_c" in r for r in rows) and any(r.startswith("w_2") for r in rows)
    assert doc.namespace["w_2"].units == ureg.mm


def test_a_ratio_shows_in_percent():
    doc = build(source='''from kip import *
# %% calc r
Q = sqrt(2.2) / 2
OS = exp(-pi / sqrt(4 * Q**2 - 1))   # -> percent
''', path="doc.py")
    assert fmt_quantity(doc.namespace["OS"]) == "5.682 %"


# -- templates ------------------------------------------------------------------------

def test_the_circuit_template_builds_from_its_cache_and_its_checks_pass(tmp_path, monkeypatch):
    import kip.spice
    from kip.scaffold import create_project
    monkeypatch.setattr(kip.spice, "_ngspice", lambda: None)   # the cache must be enough
    root = tmp_path / "filter"
    create_project(root, template="circuit")
    assert (root / "input" / "sallen_key.kicad_pcb").exists()
    assert "kip[electronics]" in (root / "pyproject.toml").read_text(encoding="utf-8")
    result = CliRunner().invoke(app, ["check", str(root / "doc.py")])
    assert result.exit_code == 0, result.output
    assert "checks 9 passed" in result.output and "error" not in result.output


def test_the_fpga_template_builds_and_its_checks_pass(tmp_path):
    from kip.scaffold import create_project
    root = tmp_path / "uart"
    create_project(root, template="fpga")
    assert (root / "input" / "uart_tx.vcd").exists()
    result = CliRunner().invoke(app, ["check", str(root / "doc.py")])
    assert result.exit_code == 0, result.output
    assert "checks 9 passed" in result.output and "error" not in result.output
