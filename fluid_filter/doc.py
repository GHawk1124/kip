"""Edit input/design.xlsx and the sections below, then run: uv run doc.py"""
from kip import *
import sympy as sp
import analysis as a
import cad

report = run_document(__file__, prepare=cad.generate, output="fluid_filter.pdf")

# %% packet component

# %% text intent stage=overview
"""Two identical CP titanium Grade 2 cups close on a five-layer stainless pack:
frame, coarse support, Dutch-twill cloth, coarse support, frame. One orbital
weld is the pressure-boundary closure. The inlet and outlet are integral stubs
that share an outside diameter and a wall; the bore is that diameter minus twice
the wall.

Fluid properties, filtration rating and the sweep points are workbook inputs.
Finished-pack resistance is not calibrated. The reference-cloth curves and the
loading curves are sensitivities. They do not qualify clean loss, loaded loss,
retention or burst.
"""

# %% draw cover "Assembled filter and axial section" stage=overview
Drawing.grid([
    ("ASSEMBLED ISOMETRIC", Drawing.load("assets/assembly.svg")),
    ("AXIAL SECTION", Drawing.load("assets/section.svg")),
], width=175, height=85)

# %% text requirements_intro stage=requirements
"""Targets below are the F100 values carried into this component. The inlet is
specified as outside diameter and wall rather than as a bore. A local stress
screen or a CAD mass is not a leak, proof, burst or retention test. Those
requirements stay open until the planned tests record evidence.
"""

# %% table "Requirements" stage=requirements
a.requirements_table(reqs, C)

# %% references "References" stage=requirements
Sources(a.sheet("References").sources())

# %% text constants_intro stage=inputs
f"""{a.fluid_note(C)}

Edit `input/design.xlsx`, then run `uv run doc.py`. The constants drive the CAD
and every calculation below. Change density, viscosity and temperature together
when the fluid state changes. @src:water
"""

# %% table "Constants" stage=inputs
C.table()

# %% text architecture stage=design
"""Seven solids: two identical turned cups, two annular frames, two coarse
supports and one fine cloth. There is no thermal moat and no separate seal ring.
The pack is trapped on the flat land. In the model the media are envelope solids,
so coining, edge sealing and the blocked-screen support capacity remain open.
"""

# %% table "Seven components" stage=design
a.bom(C)

# %% draw sheet "CAD drawing sheet" stage=design
Drawing.grid([
    ("FRONT", Drawing.load("assets/front.svg")),
    ("END", Drawing.load("assets/end.svg")),
    ("EXPLODED", Drawing.load("assets/exploded.svg")),
    ("ONE HOUSING HALF / USE TWICE", Drawing.load("assets/housing.svg")),
], width=175, height=165)

# %% text "Interfaces" stage=design section=2
f"""Exposed face {C.text('active_d')}; pack OD {C.text('frame_d')}; body OD {C.text('body_d')}.
Stub OD {C.text('stub_od')} and wall {C.text('stub_wall')}. Mass uses the revolved
housing section, the raw frame volume and the provisional cloth areal weights.
"""

# %% text flow_intro stage=preliminary
r"""Exposed area is the frame opening. Approach velocity follows continuity over
that area, $U = dot(m) / (rho A_("face"))$. The stub bore is derived; it is not
a second input. @src:design"""

# %% table "Water and geometry" stage=preliminary
C.table("rho", "mu", "temperature_F", "active_d", "stub_od", "stub_wall", "mdot_n", "mdot_s")

# %% calculation approach "Exposed area and approach velocity" stage=preliminary
flow = a.flow(C)

# %% calculation bore "Stub bore velocity and dynamic pressure" stage=preliminary
bore = a.bore_flow(C, flow)

# %% text screen_intro stage=analysis
r"""Clean loss of one screen is the viscous-plus-inertial form
$Delta p_0 = C_v mu U + C_i rho U^2$, with
$C_v = A_1 L / D_a^2$ and $C_i = A_2 L / D_a$.
$D_a$ is the measured average capillary diameter, not the filtration rating.
No extra porosity correction is applied. @src:nasa

The three published rows are individual clean cloths. A finished pack has to
include both supports and the way the stack is held. That calibration is open
on every rating. The worked calculation is the tightest published cloth,
200 x 1400. The table repeats nominal and surge loss for all three.
"""

# %% symbolic screen_model "Screen resistance" stage=analysis
Cv, Ci, mu, rho, U = sp.symbols("C_v C_i mu rho U", positive=True)
dp_screen = Cv * mu * U + Ci * rho * U**2

# %% table "Published reference cloths" stage=analysis
a.reference_table(C)

# %% calculation reference "200 x 1400 clean screen" stage=analysis
screen = a.reference_screen(C, flow)

# %% table "Reference-cloth loss on the exposed face" stage=analysis
a.screen_cases(C)

# %% text housing_intro "Housing loss" stage=analysis section=2
r"""Housing loss is separate from the cloth:
$Delta p_("housing") = K rho V_("bore")^2 / 2$.
$K$ is not taken from a fitting table or a test. The worked line uses $K = 1$.
The table lists every workbook value, and the inlet plots use the largest of
those values and say so."""

# %% calculation housing "Housing loss at K = 1" stage=analysis
housing = a.housing_loss(C, bore)

# %% table "Housing loss sensitivity" stage=analysis
a.inlet_loss_table(C)

# %% plot "Flow sensitivity — reference screens only" stage=analysis
a.flow_plot(C)

# %% plot "Inlet OD sensitivity — assumed K" stage=analysis
a.inlet_plot(C, "stub_od")

# %% plot "Inlet wall sensitivity — assumed K" stage=analysis
a.inlet_plot(C, "stub_wall")

# %% text loading_intro "Loading" stage=analysis section=2
r"""Blockage and cake are separate idealizations. For a blocked-area fraction $b$,
$F = 1 - b$ and
$Delta p_b = C_v mu U / F + C_i rho U^2 / F^2$.
The worked blockage is half the face. A cake instead adds
$mu U alpha_c m_d / A_("face")$ to the clean loss of the same cloth. The worked
cake resistance is the $10^9 "m/kg"$ sweep point. Blockage is not inferred from
dirt mass. Neither curve establishes dirt capacity, retention or media strength.
@src:design

The clean and loaded limits apply at nominal flow. Surge is shown because the
workbook asks for it. No separate surge loss limit is specified.
"""

# %% table "Loss limits and retained dirt" stage=analysis
C.table("dp_clean_limit", "dp_loaded_limit", "dirt_mass", "rating", "efficiency", "efficiency_size")

# %% calculation blockage "Half-face blockage — 200 x 1400" stage=analysis
blocked = a.blocked_drop(C, flow, screen)

# %% calculation cake "Cake at 1e9 m/kg — 200 x 1400" stage=analysis
loaded = a.loaded_drop(C, flow, screen)

# %% text "What these sensitivities say" stage=analysis section=2
f"""The 200 x 1400 cloth, alone, loses {screen.dp_n:.3g~P} at nominal flow and {screen.dp_s:.3g~P} at surge. The other two published cloths are lower. All three sit under the nominal clean limit of {C.text('dp_clean_limit')}. They are single screens. They are not the finished pack.

Housing loss at $K = 1$ is the dynamic pressure: {housing.dp_housing_n:.3g~P} nominal and {housing.dp_housing_s:.3g~P} at surge. Surge has no separate limit. At $K = 1$ the surge housing loss is already above the nominal clean limit, before any cloth is added.

Half the 200 x 1400 face blocked raises that cloth's nominal loss to {blocked.dp_blocked:.3g~P}. The illustrative cake at $10^9 "m/kg"$ adds {loaded.dp_cake:.3g~P} and brings the same cloth to {loaded.dp_loaded:.3g~P}, under the loaded limit of {C.text('dp_loaded_limit')}. Both numbers move when the cloth, the supports or $alpha_c$ change.
"""

# %% plot "Blocked-area sensitivity — reference cloth" stage=analysis
a.loading_plot(C, "blockage")

# %% plot "Cake sensitivity — assumed resistance" stage=analysis
a.loading_plot(C, "cake_alpha")

# %% text calibration "Calibration" stage=analysis section=2
r"""Fit measured clean-pack pressure drop to the two terms $mu U$ and $rho U^2$
at a known fluid state. Record $C_v$, $C_i$ and the evidence for each rating.
Micron rating alone does not supply a resistance curve. Fit housing loss on its
own, or measure the complete assembly and say which scope that test covers.
"""

# %% table "Finished-pack calibration" stage=analysis
a.rating_table(C)

# %% text pressure_intro stage=sizing
r"""The local screen is the closed-end thick cylinder at the bore,
$sigma_("VM") = (sqrt(3) p r_o^2) / (r_o^2 - r_i^2)$.
Proof stress is compared with the minimum yield strength and burst stress with
the minimum tensile strength. The stub uses the derived bore. The weld rim uses
the body outside diameter and the pocket diameter. The cone, the transitions,
the weld and fatigue are outside this comparison. It does not qualify proof or
burst. Material minima: @src:titanium."""

# %% table "Pressure and wall section" stage=sizing
C.table("p_meop", "p_proof", "p_burst", "stub_od", "stub_wall", "body_d", "pocket_d", "Sy", "Su")

# %% calculation pressure "Closed-end cylinder screen" stage=sizing
wall = a.boundary(C, flow)

# %% text "Local margins" stage=sizing section=2
f"""Every margin above is positive, so this elastic screen is inside the minimum strengths. The stub is comfortable: proof margin {wall.MS_stub_proof.magnitude:.2f}, burst margin {wall.MS_stub_burst.magnitude:.2f}. The weld rim is the closer section: proof margin {wall.MS_rim_proof.magnitude:.2f}, burst margin {wall.MS_rim_burst.magnitude:.2f}. The cone, the weld and fatigue are not in these numbers.
"""

# %% plot "Proof and burst pressure sensitivity" stage=sizing
a.pressure_plot(C)

# %% text mass_intro "Dry mass" stage=sizing section=2
"""Housing volume is the revolved half-section, checked against the CAD solid.
Frame mass uses the raw sheet, not the coined envelope. Fine-cloth thickness and
areal mass are still placeholders. The growth factor is a development reserve,
not a measured tolerance.
"""

# %% table "Mass inputs" stage=sizing
C.table("rho_ti", "rho_ss", "frame_d", "frame_raw_t", "coarse_areal_mass", "fine_areal_mass", "growth_factor", "mass_limit")

# %% calculation mass "Dry mass with the development reserve" stage=sizing
weighed = a.assembly_mass(C)

# %% text "Mass margin" stage=sizing section=2
f"""The two cups are most of the mass. Dry mass is {weighed.m_dry:.3g~P}; with the {C.text('growth_factor')} reserve it is {weighed.m_reserve:.3g~P}, against a limit of {C.text('mass_limit')} (margin {weighed.MS_mass.magnitude:.2f}). The fine-cloth areal weight is still a placeholder, so this is an estimate, not a weighed assembly.
"""

# %% text process_intro stage=manufacturing
"""The process sheet is the planned sequence. An acceptance sentence here is not
a completed inspection record.
"""

# %% table "Process" stage=manufacturing
a.sheet("Process").table(zebra=False)

# %% text test_intro stage=test
"""Empty result and evidence cells stay open. Entering a procedure in the
workbook does not close the requirement it names.
"""

# %% table "Planned tests" stage=test
a.sheet("Tests").table("id", "requirement", "procedure", "criterion", zebra=False)

# %% verify component_count stage=compliance
reqs.verify("F-10", cad.component_count(), "== 7", evidence="Generated seven-solid CAD assembly")
