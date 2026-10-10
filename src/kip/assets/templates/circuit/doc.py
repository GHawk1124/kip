"""Active filter -- a Sallen-Key low-pass from schematic to fabrication files.

The files under input/ are a KiCad project and what its tools write: the
schematic and the board, the SPICE netlist KiCad exports from the schematic
(``kicad-cli sch export netlist --format spice``), a generic op-amp model, and
the Gerber and drill files sent to a fabricator. The simulation runs in
ngspice whenever the component values change; its result is kept in
input/sallen_key.raw, so the document builds without ngspice installed.
Replace the files with your own project's.
"""

from kip import *

report = run_document(__file__, subtitle="Unity-gain Sallen-Key low-pass, 1 kHz")
schematic = Schematic.load("input/sallen_key.kicad_sch")
net = read_netlist("input/sallen_key.cir")         # exported from the schematic
board = Board.load("input/sallen_key.kicad_pcb")
fab = read_gerbers("input/fab.zip")                # Gerber and Excellon files

R_drawn = net["R1"].quantity                        # the value on the schematic
w_power = max(board.track_widths)                   # the supply tracks
W_board, H_board = board.size
W_fab, H_fab = fab.size
N_board, N_fab = len(board.holes), len(fab.holes)


def simulated(R, C_1, C_2):
    """The exported netlist with these values, run in ngspice (or read from the cache)."""
    return simulate(net.with_values(R1=R, R2=R, C1=C_1, C2=C_2), cache="input/sallen_key.raw")


def response(results):
    """Output over input, from the AC analysis."""
    return results.ac.v("out") / results.ac.v("in")


def step(results):
    """The output from the input's step at 0.5 ms."""
    return results.tran.v("out").window(0.5 * ms, 4 * ms)


# %% text scope "Scope"
"""
This report designs a second-order low-pass filter for a 1 kHz corner, checks
it in simulation, and releases its board for fabrication. The circuit is the
unity-gain Sallen-Key stage @src:sallen_key analysed in @src:sloa024; the
schematic, board and fabrication files come from KiCad @src:kicad and the
simulation from ngspice @src:ngspice.

The resistors are @val:R from the E96 series. The simulated corner is
@val:f_sim against @val:f_3dB from theory, and the step overshoots by
@val:OS_sim.
"""

# %% inputs design "Design inputs"
f_0 = 1 * kHz            # natural frequency
C_1 = 22 * nF            # feedback capacitor; C_1/C_2 sets Q
C_2 = 10 * nF            # capacitor to ground
I_supply = 0.25 * A      # most the supply tracks carry
dT_max = 10 * K          # allowed temperature rise of a track
d_fab = 0.3 * mm         # smallest hole the fabricator drills
w_fab = 0.15 * mm        # narrowest track it etches

# %% text circuit "Circuit" section=1
"""
With equal resistors, the capacitors alone set the quality factor and the
resistors then set the frequency @src:sloa024. A ratio C₁/C₂ of 2.2 gives Q
just above the Butterworth 0.707: a flat passband with a few percent of
overshoot.
"""

# %% draw schematic_drawing "Schematic"
schematic

# %% calc values "Component values" result=R,Q
R_ideal = 1 / (2 * pi * f_0 * sqrt(C_1 * C_2))   # -> kohm
R = standard_value(R_ideal, 96)                   # -> kohm
Q = sqrt(C_1 * C_2) / (2 * C_2)
f_n = 1 / (2 * pi * R * sqrt(C_1 * C_2))          # -> kHz
assert abs(R - R_drawn) <= 0.005 * R, "Schematic carries the design value"

# %% table bom "Bill of materials"
schematic.bom()

# %% text simulation "Simulation" section=1
"""
The netlist KiCad exports from the schematic is simulated with the values
computed above: an AC sweep for the frequency response and a transient for
the response to a 1 V step. The op-amp is a single-pole model with 100 dB of
open-loop gain and a 10 MHz gain-bandwidth, far beyond what a 1 kHz filter
asks of it.
"""

# %% calc sim "Simulated response" result=f_sim,OS_sim
sim = simulated(R, C_1, C_2)
H = response(sim)
v_out = step(sim)
f_3dB = f_n * sqrt(1 - 1 / (2 * Q**2) + sqrt((1 - 1 / (2 * Q**2))**2 + 1))   # -> kHz
f_sim = cutoff(H)                  # -> kHz
OS = exp(-pi / sqrt(4 * Q**2 - 1))   # -> percent
OS_sim = overshoot(v_out)          # -> percent
t_r = rise_time(v_out)             # -> us
A_stop = gain_at(H, 10 * f_0)
assert abs(f_sim - f_3dB) <= 0.02 * f_3dB, "Corner within 2 % of theory"
assert abs(OS_sim - OS) <= 1 * percent, "Overshoot within a point of theory"
assert A_stop <= -38, "At least 38 dB down a decade above f0"

# %% plot bode "Frequency response"
plot(H, label="Simulated")

# %% plot step_response "Step response"
plot(v_out, label="Output")

# %% table netlist "Netlist, as exported"
net.table()

# %% text layout "Board" section=1
"""
The board is two layers, 46 by 26 mm, with a ground pour on both sides. The
supply tracks are sized to IPC-2221 @src:ipc2221 for the current below; the
signal tracks carry microamps.
"""

# %% draw board_top "Board, top side"
board

# %% draw copper "Copper, both layers"
board.drawing(view="copper")

# %% table board_summary "Board"
board.summary_table()

# %% calc tracks "Tracks"
supply = trace_width(I=I_supply, dT=dT_max, t=35 * um)
assert w_power >= supply.w, "Supply tracks carry the supply current"
assert board.min_track >= w_fab, "Narrowest track within the fabricator's limit"

# %% text fabrication "Fabrication" section=1
"""
The Gerber and Excellon files below are what the fabricator receives. They
are read back here rather than trusted: the outline, holes and copper are
compared with the board they were plotted from.
"""

# %% draw fab_top "Fabrication files, top side"
fab

# %% table drills "Drills"
fab.drill_table()

# %% calc fab_checks "Fabrication checks"
assert abs(W_fab - W_board) <= 0.05 * mm, "Gerber outline matches the board"
assert N_fab == N_board, "Every hole is in the drill file"
assert fab.min_drill >= d_fab, "Smallest hole within the fabricator's limit"

# %% sources references "References"
Sources.load()
