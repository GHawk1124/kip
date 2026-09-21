"""Edit input/design.xlsx and the sections below; run uv run doc.py."""
from kip import *
import analysis as a
import cad

report = run_document(__file__, prepare=cad.generate, output="fluid_filter.pdf")

# %% packet component

# %% text "Design intent" stage=overview
"""Two identical titanium cups capture a stainless five-layer filter pack.
Fluid properties, filtration rating and all sweep inputs are editable.

- CP Ti Grade 2 housings; 316L frames; 316 stainless supports and Dutch-twill cloth.
- One closure weld. Integral inlet and outlet stubs share the same OD and wall.
- Calibration remains OPEN. Reference-screen and loading curves are sensitivities.
"""

# %% table "Requirements" stage=requirements
a.requirements_table(reqs, C)

# %% references "References" stage=requirements
Sources(a.sheet("References").sources())

# %% table "Operating point" stage=inputs
a.inputs_table(C)

# %% text "Fluid state" stage=inputs
f"{a.fluid_note(C)}"

# %% text "Bore and exposed face" stage=preliminary
r"""$d_i=d_o-2t$, $A_("face")=pi d_("face")^2/4$,
and $U=dot(m)/(rho A_("face"))$."""

# %% table "Preliminary results" stage=preliminary
a.flow_table(C)

# %% table "Inlet velocity and dynamic pressure" stage=preliminary
a.inlet_table(C)

# %% table "Housing loss sensitivity" stage=preliminary
a.inlet_loss_table(C)

# %% text "Pressure boundary" stage=sizing
r"""The closed-end thick-cylinder screen uses
$sigma_("VM") = sqrt(3) p r_o^2 / (r_o^2-r_i^2)$ at the bore.
Compare proof stress with yield and burst stress with minimum tensile strength.
These local elastic comparisons exclude the cone, transitions, weld and fatigue.
They do not establish proof or burst qualification. Material minima: @src:titanium."""

# %% table "Local pressure screens" stage=sizing
a.pressure_table(C)

# %% table "Mass estimate" stage=sizing
a.mass_table(C)

# %% drawing "Assembly and axial section" stage=design
Drawing.grid([
    ("ASSEMBLED", Drawing.load("assets/assembly.svg")),
    ("AXIAL SECTION", Drawing.load("assets/section.svg")),
], width=172, height=85)

# %% table "Seven components" stage=design
a.bom(C)

# %% text "Interfaces" stage=design
f"""Exposed face diameter {C.text('active_d')}; pack OD {C.text('frame_d')}; body OD {C.text('body_d')}.
Mass uses revolved housing volume, raw frame volume and provisional cloth areal weights.
Coining, media thickness, edge sealing and blocked-screen support capacity remain OPEN."""

# %% text "Clean screen model" stage=analysis
r"""Use superficial velocity $U=dot(m)/(rho A_("face"))$ and
$Delta p_0=C_v mu U+C_i rho U^2$.
For the published cloths, $C_v=A_1 L/D_a^2$ and $C_i=A_2 L/D_a$.
$D_a$ is measured average capillary diameter, distinct from filtration rating.
No additional porosity correction is applied. @src:nasa

The reference curves represent individual clean screens. A finished-pack fit
must include the two support layers and assembly effects. Housing loss is separate:
$Delta p_("housing")=K rho V_("bore")^2/2$. Its coefficient is also uncalibrated."""

# %% table "Published reference cloths" stage=analysis
a.reference_table(C)

# %% table "Micron-rating sweep" stage=analysis
a.rating_table(C)

# %% table "Selected finished-pack prediction" stage=analysis
a.selected_table(C)

# %% plot "Flow sensitivity — reference screens only" stage=analysis
a.flow_plot(C)

# %% plot "Inlet OD sensitivity — assumed K" stage=analysis
a.inlet_plot(C, "stub_od")

# %% plot "Inlet wall sensitivity — assumed K" stage=analysis
a.inlet_plot(C, "stub_wall")

# %% plot "Proof and burst pressure sensitivity" stage=analysis
a.pressure_plot(C)

# %% text "Loading sensitivities" stage=analysis
r"""For blocked-area fraction $b$, let $F=1-b$ and use
$Delta p_b=C_v mu U/F+C_i rho U^2/F^2$.
Alternatively, a cake adds $mu U alpha_c m_d/A_("face")$ to clean loss.
The curves below apply each idealization separately to one reference cloth.
Blockage is not inferred from dirt mass. Cake resistance, retention performance
and media strength require test data. @src:design"""

# %% plot "Blocked-area sensitivity — reference cloth" stage=analysis
a.loading_plot(C, "blockage")

# %% plot "Cake sensitivity — assumed resistance" stage=analysis columnbreak=true
a.loading_plot(C, "cake_alpha")

# %% text "Calibration and limits" stage=analysis
"""Fit measured clean pack data to the two terms $mu U$ and $rho U^2$ at a known
fluid state. Record both coefficients and evidence for each rating. Micron rating
alone supplies no resistance curve. Fit housing loss separately or measure the
complete assembly and identify that scope explicitly.

The clean and loaded loss requirements apply at nominal flow. Surge curves show
sensitivity; no separate surge loss limit has been specified."""

# %% table "Planned verification" stage=test
a.test_table()

# %% verify component_count stage=compliance
reqs.verify("F-10", cad.component_count(), "== 7", evidence="Generated seven-solid CAD assembly")
