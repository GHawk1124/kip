from kip import *
from pathlib import Path
import json
import sympy as sp
import handcalcs
handcalcs.set_option("custom_symbols", {"mdot": r"\dot{m}"})
import runpy
ROOT=Path.cwd()
INPUTS=runpy.run_path(str(ROOT / "inputs.py"))
C,ROWS=INPUTS["C"],INPUTS["ROWS"]
CAD=json.loads((ROOT / "output/cad/metadata.json").read_text())
SOURCE_DATA=json.loads((ROOT / "sources.json").read_text(encoding="utf-8"))
for row in INPUTS["SUPPLIERS"]:
    SOURCE_DATA[row["source_key"]]={"title":row["supplier_item"],"url":row["source_url"],"note":row["catalog_basis"]}
def input_symbol(key):
    return Math("dot(m)_" + key.rsplit("_",1)[1]) if key.startswith("mdot_") else Symbol({"Cv_f":"C_vf", "Ci_f":"C_if", "Cv_c":"C_vc", "Ci_c":"C_ic"}.get(key,key))
def asset(name,width=170,height=None):
    return Drawing(svg=(ROOT/"assets"/name).read_bytes(),width=width,height=height)


# %% text scope "Design intent" wrap_title=true
'[insert text here]'


# %% draw cover "F100 / assembled isometric and cutaway" caption=""
cover=asset('cover_pair.svg',175,78)


# %% text constant_intro "Calculation constants"
'Edit input/constants.xlsx, the editable source of this table, then run uv run generate.py. All dimensional and engineering inputs below are read from that table. Derived CAD volume is regenerated from those dimensions. Changing temperature also requires updating the corresponding water properties.'


# %% table constants "Constants" pagebreak=true
constants = Table([Column("key", "Symbol", math=True, align="left"), Column("value", "Value / unit"), Column("definition", "Definition / basis", align="left")], [(input_symbol(r["key"]), f"{float(r['value']):g} {r['unit']}", r["description"] + "; " + r["basis"]) for r in ROWS])


# %% text requirements "01 / Requirements and interpretation" pagebreak=true
'[insert text here]'


# %% table reqs "Requirement-by-requirement assessment"
reqs=Table(['ID / requirement', 'Target', 'Assessment'],[('R01 / Housing MEOP', '650 psi', '[insert text here]'), ('R02 / Housing proof', '1300 psi', '[insert text here]'), ('R03 / Housing burst', '2600 psi', '[insert text here]'), ('R04 / Micron rating', '5 um', '[insert text here]'), ('R05 / Efficiency', '99.9 percent at 3 um', '[insert text here]'), ('R06 / Nominal flow', '0.14 lb/s', '[insert text here]'), ('R07 / Surge flow', '0.47 lb/s', '[insert text here]'), ('R08 / Clean pressure drop', '5 psi', '[insert text here]'), ('R09 / Retained dirt', '0.318 g', '[insert text here]'), ('R10 / Loaded pressure drop', '18 psi', '[insert text here]'), ('R11 / Dry mass', '1 lb', '[insert text here]'), ('R12 / Water temperature', '70 degF', '[insert text here]'), ('R13 / Component count', 'Seven', '[insert text here]')])


# %% text architecture "02 / Architecture" pagebreak=true
'[insert text here]'


# %% table bom "Seven-piece bill of materials"
bom=Table(['Component', 'Qty', 'Definition'],[('Housing half', '2', 'CP Ti Grade 2; identical; integral weld stubs'), ('Annular frame', '2', '316L; OD 70, ID 58, raw thickness 0.2 mm'), ('Coarse support', '2', '40 x 40; assembled thickness 0.48 mm'), ('Fine cloth', '1', 'Dutch twill candidate; thickness 0.18 mm assumed')])


# %% text exploded "03 / Assembly exploded"
'[insert text here]'


# %% draw exploded_fig "Seven components" caption=""
exploded_fig=asset('exploded_render_embed.svg',170,150)


# %% text drawing_sheet "05 / CAD drawing sheet" pagebreak=true
'[insert text here]'


# %% draw drawings "All four drawings" caption=""
drawings=asset('drawing_sheet.svg',175,170)


# %% text element "06 / Filter element" pagebreak=true
'[insert text here]'


# %% table suppliers "Mesh sourcing"
suppliers=Table(['Supplier / item', 'Catalog basis', 'Assessment'],[('GKD / Dutch-twilled family', '5 um end of family; 316L listed; exact construction needs RFQ', '[insert text here]'), ('TWP / 040X040T0100', 'Coarse 40 x 40, 0.010 in wire; T316', '[insert text here]'), ('Darby / 40316.010PL', 'Coarse 40 x 40, 0.010 in wire; T316', '[insert text here]'), ('Dorstener / custom fabrication', 'Custom cloth and element fabrication lead', '[insert text here]')])


# %% text source_trail "Source trail"
'[insert text here]\n\n@src:gkd @src:twp @src:darby @src:dwt'


# %% text flow_basis "08 / Flow basis and clean-screen equation" pagebreak=true
'[insert text here]'


# %% table fluidinputs "Water and geometry" 
rho_w = C["rho_w"] * kg / m**3
mu_w = C["mu_w"] * Pa * s
d_face = C["active_d"] * mm
d_bore = C["stub_id"] * mm
mdot_n = C["mdot_n"] * lb / s
mdot_s = C["mdot_s"] * lb / s
fluid_table = Table(["Symbol", "Value"], [(Symbol("rho_w"), rho_w), (Symbol("mu_w"), f"{C['mu_w']:g} Pa s"), (Symbol("d_face"), d_face), (Symbol("d_bore"), d_bore), (Math("dot(m)_n"), mdot_n), (Math("dot(m)_s"), mdot_s)])


# %% calc approach "Exposed area and approach velocity" unit="A_face=mm**2, U_n=m/s, U_s=m/s"
A_face = pi * d_face**2 / 4
U_n = mdot_n / (rho_w * A_face)
U_s = mdot_s / (rho_w * A_face)


# %% symbolic flowmodel "Screen-specific resistance model" 
Cv, Ci, visc, dens, velocity = sp.symbols("C_v C_i mu rho U", positive=True)
dp_screen = Cv * visc * velocity + Ci * dens * velocity**2


# %% text equationscope "Use of the supplied equations"
'[insert text here]\n\n$C_v = A_1 L / D_a^2$\n\n$C_i = A_2 L / D_a$'


# %% text surge "09 / Simplified surge estimation" pagebreak=true
'[insert text here]'


# %% text resistance_basis "Assumed resistance coefficients"
'Use the assumed values below for Dutch twill and the combined coarse pair. These are preliminary inputs, not measured supplier data. The viscous terms scale with viscosity and velocity; the inertial terms scale with density and velocity squared. Housing loss uses bore velocity: $Delta p_"body" = K_"body" rho V_"bore"^2 / 2$.'


# %% table hyd_inputs "Coefficient definitions / constants workbook" 
C_vf = C["Cv_f"] / m
C_if = C["Ci_f"]
C_vc = C["Cv_c"] / m
C_ic = C["Ci_c"]
K_body = C["K_body"]
coefficient_table = Table([Column("symbol", "Symbol", align="left"), Column("value", "Assumed value"), Column("definition", "Definition", align="left")], [(Symbol("C_vf"), C_vf, "Viscous resistance of the single fine Dutch-twill layer"), (Symbol("C_if"), C_if, "Dimensionless inertial resistance of the single fine layer"), (Symbol("C_vc"), C_vc, "Combined viscous resistance of both coarse supports"), (Symbol("C_ic"), C_ic, "Combined dimensionless inertial resistance of both coarse supports"), (Symbol("K_body"), K_body, "Dimensionless inlet, outlet and transition loss coefficient; excludes mesh")])


# %% calc hyd_surge "Surge assembly pressure drop" unit="A_bore=mm**2, V_bore=m/s, DP_s=psi"
A_bore = pi * d_bore**2 / 4
V_bore = mdot_s / (rho_w * A_bore)
DP_s = (C_vf + C_vc) * mu_w * U_s + (C_if + C_ic) * rho_w * U_s**2 + K_body * rho_w * V_bore**2 / 2


# %% calc hyd_nominal "Nominal assembly pressure drop" unit="V_nom=m/s, DP_n=psi"
V_nom = mdot_n / (rho_w * A_bore)
DP_n = (C_vf + C_vc) * mu_w * U_n + (C_if + C_ic) * rho_w * U_n**2 + K_body * rho_w * V_nom**2 / 2


# %% text dirt "11 / Loaded pressure drop" pagebreak=true
'[insert text here]'


# %% text cakemodel "Series-cake equation"
'[insert text here]\n\n$ Delta p_l = C_v mu U + C_i rho U^2 + mu U alpha_c m_d / A_f $'


# %% given cakeinputs "Cake inputs / constants table" 
alpha_c = C["alpha_c"] * m / kg
m_d = C["dirt_mass"] * g


# %% calc loaded "Loaded assembly pressure drop" unit=psi
DP_loaded_n = DP_n + mu_w * U_n * alpha_c * m_d / A_face
DP_loaded_s = DP_s + mu_w * U_s * alpha_c * m_d / A_face


# %% text pressure "12 / Housing pressure screening" pagebreak=true
'[insert text here]'


# %% given pressinput "Pressure and weld-rim section" unit="p_meop=MPa, p_proof=MPa, p_burst=MPa"
p_meop = C["p_meop"] * psi
p_proof = C["p_proof"] * psi
p_burst = C["p_burst"] * psi
r_i = C["pocket_d"] / 2 * mm
r_o = C["body_d"] / 2 * mm
S_y = C["Sy"] * MPa
S_u = C["Su"] * MPa


# %% calc lame "Closed-end thick-cylinder check at the weld rim" unit="sigma_h=MPa, sigma_z=MPa, sigma_r=MPa, sigma_vm=MPa" precision=2
sigma_h = p_burst * (r_o**2 + r_i**2) / (r_o**2 - r_i**2)
sigma_z = p_burst * r_i**2 / (r_o**2 - r_i**2)
sigma_r = -p_burst
sigma_vm = (((sigma_h-sigma_z)**2 + (sigma_z-sigma_r)**2 + (sigma_r-sigma_h)**2) / 2)**0.5


# %% text detail "Detail B" pagebreak=true
'[insert text here]'


# %% draw detail_b "Housing and pack / section detail" caption="Circular section from Build123d. Gold: solid frames; blue: media envelopes."
detail_b=asset('detail_circle.svg',175,72)


# %% text mass "22 / Full mass calculations" pagebreak=true
'[insert text here]'


# %% given mass_inputs "Density, sheet and cloth inputs / constants table" 
V_half = CAD["housing_volume_mm3"] * mm**3
rho_ti = C["rho_ti"] * kg / m**3
rho_ss = C["rho_ss"] * kg / m**3
d_pack = C["frame_d"] * mm
t_frame = C["frame_raw_t"] * mm
w_coarse = C["coarse_areal_mass"] * kg / m**2
w_fine = C["fine_areal_mass"] * kg / m**2
growth = C["growth_factor"]
m_limit = C["mass_limit"] * lb


# %% calc part_mass "Housing, frames and mesh masses" unit="A_pack=mm**2, V_frame=mm**3, m_housings=g, m_frames=g, m_coarse=g, m_fine=g"
A_pack = pi * d_pack**2 / 4
V_frame = pi * (d_pack**2 - d_face**2) * t_frame / 4
m_housings = 2 * V_half * rho_ti
m_frames = 2 * V_frame * rho_ss
m_coarse = 2 * A_pack * w_coarse
m_fine = A_pack * w_fine


# %% calc mass_calc "Dry finished mass with a development reserve" unit="m_dry=lb, m_reserve=lb"
m_dry = m_housings + m_frames + m_coarse + m_fine
m_reserve = growth * m_dry
MS_mass = m_limit / m_reserve - 1


# %% text mass_scope "Mass scope"
'[insert text here]'


# %% text references_intro "24 / References" pagebreak=true
'[insert text here]'


# %% sources references "References" 
refs = Sources(**{key: Source(**value) for key, value in SOURCE_DATA.items()})
