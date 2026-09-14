"""Edit the sections below, then run: uv run doc.py"""
from kip import *
import sympy as sp
import analysis
import cad
from analysis import C, ROWS

# Document settings; layout and title wrapping are Kip defaults.
report = run_document(
    __file__, prepare=cad.generate, output="simple_filter.pdf",
    title="F100 / WATER FILTER", subtitle="Seven components. One pressure-boundary weld.",
    project="Water filtration", document="F100-SIMPLE-001", font_size=9,
    author="Engineering concept", checker="Review required", revision="S0", date="2026-09-14",
    marking="DEVELOPMENT CONCEPT / NOT QUALIFIED FOR SERVICE",
)

# Editable spreadsheets and references.
requirements = read_records("input/requirements.xlsx")
suppliers = read_records("input/mesh_suppliers.xlsx")
if len({r["id"] for r in requirements}) != len(requirements):
    raise ValueError("Duplicate requirement ID")
for row in requirements:
    for key in (row["constant_key"], row["qualifier_key"]):
        if key and key not in C:
            raise ValueError(f"Unknown requirement constant: {key}")
    if not row["constant_key"] and not row["target_text"]:
        raise ValueError(f"Missing target: {row['id']}")
if len({r["source_key"] for r in suppliers}) != len(suppliers):
    raise ValueError("Duplicate supplier source key")
sources = Sources.load()
for row in suppliers:
    sources[row["source_key"]] = Source(title=row["supplier_item"], url=row["source_url"], note=row["catalog_basis"])
cad_info = cad.metadata()
symbols = {"Cv_f":"C_vf", "Ci_f":"C_if", "Cv_c":"C_vc", "Ci_c":"C_ic"}
values = {r["key"]: f"{r['value']:g} {r['unit']}" for r in ROWS}


# %% text scope "Design intent"
"""
[insert text here]
"""

# %% draw cover "F100 / assembled isometric and cutaway"
cover = Drawing.grid([
    ("ASSEMBLED ISOMETRIC", Drawing.load("assets/hero.png")),
    ("HOUSING AND PACK / CUTAWAY ISO", Drawing.load("assets/cutaway.png")),
], width=175, height=78)

# %% text constant_intro "Calculation constants"
"""
Edit the three Excel files in input/, then run uv run doc.py. Constants drive CAD and calculations; requirements reference those constants. Update water properties consistently when changing temperature.
"""

# %% table constants "Constants" pagebreak=true
constants = Table([
    Column("key", "Symbol", math=True, align="left"), "Value / unit",
    Column("definition", "Definition / basis", align="left"),
], [(Symbol(symbols.get(r["key"], r["key"])), values[r["key"]],
     r["description"] + "; " + r["basis"]) for r in ROWS])

# %% text requirements "01 / Requirements and interpretation" pagebreak=true
"""
[insert text here]
"""

# %% table reqs "Requirement-by-requirement assessment"
reqs = Table(["ID / requirement", "Target", "Assessment"], [
    (r["id"] + " / " + r["requirement"],
     (values[r["constant_key"]] if r["constant_key"] else r["target_text"])
     + (" at " + values[r["qualifier_key"]] if r["qualifier_key"] else ""),
     r["assessment"]) for r in requirements
])

# %% text architecture "02 / Architecture" pagebreak=true
"""
[insert text here]
"""

# %% table bom "Seven-piece bill of materials"
bom=Table(['Component', 'Qty', 'Definition'],[('Housing half', '2', 'CP Ti Grade 2; identical; integral weld stubs'), ('Annular frame', '2', f"316L; OD {values['frame_d']}, ID {values['active_d']}, raw thickness {values['frame_raw_t']}"), ('Coarse support', '2', f"40 x 40; assembled thickness {values['coarse_t']}"), ('Fine cloth', '1', f"Dutch twill candidate; thickness {values['fine_t']} assumed")])

# %% text exploded "03 / Assembly exploded"
"""
[insert text here]
"""

# %% draw exploded_fig "Seven components"
exploded = Drawing.load("assets/exploded_render.png", width=170, height=150)

# %% text drawing_sheet "05 / CAD drawing sheet" pagebreak=true
"""
[insert text here]
"""

# %% draw drawings "All four drawings"
drawings = Drawing.grid([
    ("FRONT", Drawing.load("assets/front.svg")),
    ("SECTION A-A / CENTER PLANE", Drawing.load("assets/section_cad.svg")),
    ("END", Drawing.load("assets/end.svg")),
    ("ONE HOUSING HALF / USE TWICE", Drawing.load("assets/housing_iso.svg")),
], width=175, height=170)

# %% text element "06 / Filter element" pagebreak=true
"""
[insert text here]
"""

# %% table suppliers "Mesh sourcing"
mesh_sources = Table(["Supplier / item", "Catalog basis", "Assessment"], [
    (r["supplier_item"], r["catalog_basis"], r["assessment"]) for r in suppliers
])

# %% text source_trail "Source trail"
"""[insert text here]\n\n@src:gkd @src:twp @src:darby @src:dwt"""

# %% text flow_basis "08 / Flow basis and clean-screen equation" pagebreak=true
"""
[insert text here]
"""

# %% table fluidinputs "Water and geometry"
water_inputs = Table(["Symbol", "Value"], [
    (Symbol("rho_w"), flow.rho_w), (Symbol("mu_w"), values["mu_w"]),
    (Symbol("d_face"), flow.d_face), (Symbol("d_bore"), values["stub_id"]),
    (Symbol("mdot_n"), flow.mdot_n), (Symbol("mdot_s"), flow.mdot_s),
])

# %% calculation approach "Exposed area and approach velocity"
flow = analysis.flow(C)

# %% symbolic flowmodel "Screen-specific resistance model"
Cv, Ci, visc, dens, velocity = sp.symbols("C_v C_i mu rho U", positive=True)
dp_screen = Cv * visc * velocity + Ci * dens * velocity**2

# %% text equationscope "Use of the supplied equations"
"""
[insert text here]

$C_v = A_1 L / D_a^2$

$C_i = A_2 L / D_a$
"""

# %% text surge "09 / Simplified surge estimation" pagebreak=true
"""
[insert text here]
"""

# %% text resistance_basis "Assumed resistance coefficients"
"""
Use the assumed values below for Dutch twill and the combined coarse pair. These are preliminary inputs, not measured supplier data. The viscous terms scale with viscosity and velocity; the inertial terms scale with density and velocity squared. Housing loss uses bore velocity: $Delta p_"body" = K_"body" rho V_"bore"^2 / 2$.
"""

# %% table hyd_inputs "Coefficient definitions / constants workbook"
resistance = Table(["Symbol", "Assumed value", "Definition"], [
    (Symbol("C_vf"), values["Cv_f"], "Viscous resistance of the single fine Dutch-twill layer"),
    (Symbol("C_if"), values["Ci_f"], "Dimensionless inertial resistance of the fine layer"),
    (Symbol("C_vc"), values["Cv_c"], "Combined viscous resistance of both coarse supports"),
    (Symbol("C_ic"), values["Ci_c"], "Combined inertial resistance of both coarse supports"),
    (Symbol("K_body"), values["K_body"], "Dimensionless inlet, outlet and transition loss; excludes mesh"),
])

# %% calculation hyd_surge "Surge assembly pressure drop"
surge = analysis.clean(C, flow, flow.mdot_s)

# %% calculation hyd_nominal "Nominal assembly pressure drop"
nominal = analysis.clean(C, flow, flow.mdot_n)

# %% text dirt "11 / Loaded pressure drop" pagebreak=true
"""
[insert text here]
"""

# %% text cakemodel "Series-cake equation"
"""
[insert text here]

$ Delta p_l = C_v mu U + C_i rho U^2 + mu U alpha_c m_d / A_f $
"""

# %% table cakeinputs "Cake inputs / constants table"
cake_inputs = Table(["Symbol", "Value"], [
    (Symbol("alpha_c"), values["alpha_c"]), (Symbol("m_d"), values["dirt_mass"]),
])

# %% calculation loaded "Loaded assembly pressure drop"
loaded = analysis.loaded(C, flow, nominal, surge)

# %% text pressure "12 / Housing pressure screening" pagebreak=true
"""
[insert text here]
"""

# %% table pressinput "Pressure and weld-rim section"
pressure_inputs = Table(["Input", "Value"], [
    ("MEOP", values["p_meop"]), ("Proof", values["p_proof"]), ("Burst", values["p_burst"]),
    (Symbol("r_i"), C["pocket_d"] / 2 * mm), (Symbol("r_o"), C["body_d"] / 2 * mm),
    (Symbol("S_y"), values["Sy"]), (Symbol("S_u"), values["Su"]),
])

# %% calculation lame "Closed-end thick-cylinder check at the weld rim"
pressure = analysis.pressure(C)

# %% text detail "Detail B" pagebreak=true
"""
[insert text here]
"""

# %% draw detail_b "Housing and pack / section detail"
detail = Drawing.load("assets/detail_circle.svg", width=175, height=72, caption="Circular section from Build123d. Gold: solid frames; blue: media envelopes.")

# %% text mass "22 / Full mass calculations" pagebreak=true
"""
[insert text here]
"""

# %% table mass_inputs "Density, sheet and cloth inputs / constants table"
volume = Table(["Input", "Value"], [
    (Symbol("V_half"), cad_info["housing_volume_mm3"] * mm**3),
])

# %% calculation mass_calc "Dry finished mass with a development reserve"
mass = analysis.mass(C, cad_info["housing_volume_mm3"])
analysis.save_results(flow=flow, nominal=nominal, surge=surge, loaded=loaded, pressure=pressure, mass=mass)

# %% text mass_scope "Mass scope"
"""
[insert text here]
"""

# %% text references_intro "24 / References" pagebreak=true
"""
[insert text here]
"""

# %% sources references "References"
references = sources
