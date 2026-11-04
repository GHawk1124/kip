"""UART transmitter -- an FPGA design from source to timing closure.

The files under input/ are an iCE40 design and what its open toolchain writes:
the Verilog source and its testbench, the iCEBreaker pin constraints, Yosys's
cell count (``yosys -p "synth_ice40 -top uart_tx; tee -o stat.json stat -json"``),
nextpnr's report (``nextpnr-ice40 --up5k --package sg48 --pcf pins.pcf
--report report.json``), and the synthesised transmitter sending one byte, as
a value-change dump. Replace them with your own project's.
"""

from kip import *

report = run_document(__file__, subtitle="8N1 serial at 115 200 baud on an iCE40UP5K")
rtl = read_hdl("input/uart_tx.v")["uart_tx"]
pins = read_constraints("input/pins.pcf")
synthesis = read_utilization("input/stat.json")      # Yosys: cells by type
placed = read_utilization("input/report.json")       # nextpnr: cells used of those on the die
timing = read_timing("input/report.json")
sim = read_vcd("input/uart_tx.vcd")

f_rtl = (rtl.parameter("CLK_HZ") * Hz).to("MHz")      # what the source is built for
baud_rtl = (rtl.parameter("BAUD") * Hz).to("kHz")
N_ports, N_pins = rtl.io_bits, len(pins.pins)
N_LC, N_die = placed["ICESTORM_LC"], placed.available("ICESTORM_LC")
N_IO = placed["SB_IO"]
tx, busy = sim["tx"], sim["busy"]

# %% text scope "Scope"
"""
This report releases a UART transmitter for the iCEBreaker board
@src:icebreaker: eight data bits, no parity and one stop bit, sent at
115 200 baud from the board's 12 MHz oscillator. It is synthesised by Yosys
@src:yosys and placed and routed by nextpnr @src:nextpnr for the Lattice
iCE40UP5K @src:ice40up.

Each bit lasts @val:N_div clock cycles, which puts the line rate @val:e_baud
off nominal. The placed design runs at up to @val:f_max and fills
@val:u_LC of the logic cells.
"""

# %% inputs design "Design inputs"
f_clk = 12 * MHz         # board oscillator
baud = 115.2 * kHz       # line rate, bits per second
N_frame = 10             # bits per frame: start, eight data, stop
n_os = 16                # receiver's samples per bit
u_max = 25 * percent     # share of the logic cells this block may take

# %% draw symbol "The module"
rtl

# %% table ports "Ports"
rtl.table()

# %% text bit_timing "Bit timing" section=1
"""
The transmitter times each bit by counting clock cycles. The count is the
clock frequency over the line rate rounded to the nearest whole cycle, as the
source computes its divider, and the rounding leaves the rate slightly off.

A receiver finds the start bit's falling edge to within one of its samples,
then reads each bit at its middle; the frame is lost if the two ends' clocks
drift apart by the rest of half a bit before the stop bit is read. The
transmitter may take half of that budget, the receiver the other half.
"""

# %% calc divider "Divider and rate error" result=N_div,e_baud
N_div = floor(f_clk / baud + 1 / 2)
t_bit = N_div / f_clk                                 # -> us
baud_actual = f_clk / N_div                           # -> kHz
e_baud = (baud_actual - baud) / baud                  # -> percent
e_frame = (1 / 2 - 1 / n_os) / (N_frame - 1 / 2)     # -> percent
assert abs(e_baud) <= e_frame / 2, "Rate within the transmitter's half of the budget"
assert f_rtl == f_clk, "Source built for this clock"
assert baud_rtl == baud, "Source built for this rate"

# %% draw frame "An 8N1 frame carrying 0x4B, least significant bit first"
wavedrom({"signal": [
    {"name": "tx", "wave": "101.010.101."},
    {"name": "bit", "wave": "x==========x",
     "data": ["start", "d0", "d1", "d2", "d3", "d4", "d5", "d6", "d7", "stop"]},
]})

# %% text simulation "Simulation" section=1
"""
The testbench (input/tb.v) releases reset and offers one byte, 0x4B. The
design as Yosys synthesised it was stepped one clock at a time and its
signals written out; the line below is read from that dump, not assumed from
the source.
"""

# %% draw waveform "Sending one byte"
sim.timing("rst_n", "valid", "ready", "busy", "tx", "bit_index", end=92 * us)

# %% calc measured "Measured on the line" result=t_start
t_start = pulse_width(tx, 0)                          # -> us
t_busy = pulse_width(busy, 1)                         # -> us
assert abs(t_start - t_bit) <= 0.001 * t_bit, "Start bit lasts the designed bit time"
assert abs(t_busy - N_frame * t_bit) <= 0.001 * t_bit, "Frame lasts ten bit times"

# %% text implementation "Implementation" section=1
"""
Yosys maps the design onto the iCE40's four-input look-up tables, flip-flops
and carry chains. nextpnr packs them into logic cells, each one look-up table
with its flip-flop and carry, places those on the die and routes them, then
reports the fastest clock the routed design meets @src:nextpnr.
"""

# %% table cells "Cells after synthesis"
synthesis.table()

# %% table resources "Resources after placement"
placed.table(titles={"ICESTORM_LC": "Logic cells", "SB_IO": "I/O pins", "SB_GB": "Global buffers"})

# %% table pinout "Pin-out"
pins.table()

# %% table timing_summary "Timing after routing"
timing.table()

# %% calc fit "Fit and timing" result=f_max,u_LC
f_max = fmax(timing)                                  # -> MHz
t_slack = 1 / f_clk - 1 / f_max                       # -> ns
u_LC = N_LC / N_die                                   # -> percent
assert f_max >= f_clk, "Meets timing at the board clock"
assert u_LC <= u_max, "Within its share of the logic cells"
assert N_pins == N_ports, "Every port bit has a pin"
assert N_IO == N_ports, "Every port bit is placed on an I/O"

# %% sources references "References"
Sources.load()
