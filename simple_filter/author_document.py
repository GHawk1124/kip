"""Kip template; named narrative sections intentionally remain placeholders."""
import json
from inputs import ROOT,C,ROWS,REQS,SUPPLIERS
parts=['from kip import *\nfrom pathlib import Path\nimport json\nimport sympy as sp\nimport runpy\nROOT=Path.cwd()\nINPUTS=runpy.run_path(str(ROOT / "inputs.py"))\nC,ROWS=INPUTS["C"],INPUTS["ROWS"]\nCAD=json.loads((ROOT / "output/cad/metadata.json").read_text())\nSOURCE_DATA=json.loads((ROOT / "sources.json").read_text(encoding="utf-8"))\nfor row in INPUTS["SUPPLIERS"]:\n    SOURCE_DATA[row["source_key"]]={"title":row["supplier_item"],"url":row["source_url"],"note":row["catalog_basis"]}\ndef asset(name,width=170,height=None):\n    return Drawing(svg=(ROOT/"assets"/name).read_bytes(),width=width,height=height)\n']
def text(bid,title,new=False,body='[insert text here]'):
    parts.append(f'\n# %% text {bid} "{title}"'+(' wrap_title=true' if bid=='scope' else '')+(' pagebreak=true' if new else '')+'\n'+repr(body)+'\n')
def table(bid,title,heads,rows):
    parts.append(f'\n# %% table {bid} "{title}"\n{bid}=Table({heads!r},{rows!r})\n')
def code(bid,title,body,kind='calc',meta=''):
    parts.append(f'\n# %% {kind} {bid} "{title}" {meta}\n{body}\n')
def figure(bid,title,name,width=170,height=None,caption=''):
    parts.append(f'\n# %% draw {bid} "{title}" caption={json.dumps(caption)}\n{bid}=asset({name!r},{width},{height!r})\n')
text('scope','Design intent')
figure('cover','F100 / assembled isometric and cutaway','cover_pair.svg',175,78)
text('constant_intro','Calculation constants',body='Edit input/constants.xlsx, the editable source of this table, then run uv run generate.py. All dimensional and engineering inputs below are read from that table. Derived CAD volume is regenerated from those dimensions. Changing temperature also requires updating the corresponding water properties.')
code('constants','Constants', 'constants = Table([Column("key", "Symbol", math=True, align="left"), Column("value", "Value / unit"), Column("definition", "Definition / basis", align="left")], [(r["key"], f"{float(r[\'value\']):g} {r[\'unit\']}", r["description"] + "; " + r["basis"]) for r in ROWS])',kind='table',meta='pagebreak=true')
text('requirements','01 / Requirements and interpretation',True)
units={r['key']:r['unit'] for r in ROWS}
def target(row):
    key=row['constant_key']
    value=f"{C[key]:g} {units[key]}" if key else row['target_text']
    q=row['qualifier_key']
    if q: value+=f" at {C[q]:g} {units[q]}"
    return value
table('reqs','Requirement-by-requirement assessment',['ID / requirement','Target','Assessment'],[(r['id']+' / '+r['requirement'],target(r),r['assessment']) for r in REQS])
text('architecture','02 / Architecture',True)
table('bom','Seven-piece bill of materials',['Component','Qty','Definition'],[('Housing half','2','CP Ti Grade 2; identical; integral weld stubs'),('Annular frame','2',f"316L; OD {C['frame_d']:g}, ID {C['active_d']:g}, raw thickness {C['frame_raw_t']:g} mm"),('Coarse support','2',f"40 x 40; assembled thickness {C['coarse_t']:g} mm"),('Fine cloth','1',f"Dutch twill candidate; thickness {C['fine_t']:g} mm assumed")])
text('exploded','03 / Assembly exploded')
figure('exploded_fig','Seven components','exploded_render_embed.svg',170,150)
text('drawing_sheet','05 / CAD drawing sheet',True)
figure('drawings','All four drawings','drawing_sheet.svg',175,170)
text('element','06 / Filter element',True)
table('suppliers','Mesh sourcing',['Supplier / item','Catalog basis','Assessment'],[(r['supplier_item'],r['catalog_basis'],r['assessment']) for r in SUPPLIERS])
text('source_trail','Source trail',body='[insert text here]\n\n'+' '.join('@src:'+r['source_key'] for r in SUPPLIERS))
text('flow_basis','08 / Flow basis and clean-screen equation',True)
code('fluidinputs','Water and geometry','rho_w = C["rho_w"] * kg / m**3\nmu_w = C["mu_w"] * Pa * s\nd_face = C["active_d"] * mm\nd_bore = C["stub_id"] * mm\nmdot_n = C["mdot_n"] * lb / s\nmdot_s = C["mdot_s"] * lb / s',kind='given')
code('approach','Exposed area and approach velocity','A_face = pi * d_face**2 / 4\nU_n = mdot_n / (rho_w * A_face)\nU_s = mdot_s / (rho_w * A_face)',meta='unit="A_face=mm**2, U_n=m/s, U_s=m/s"')
code('flowmodel','Screen-specific resistance model','Cv, Ci, visc, dens, velocity = sp.symbols("C_v C_i mu rho U", positive=True)\ndp_screen = Cv * visc * velocity + Ci * dens * velocity**2',kind='symbolic')
text('equationscope','Use of the supplied equations',body='[insert text here]\n\n$C_v = A_1 L / D_a^2$\n\n$C_i = A_2 L / D_a$')
text('surge','09 / Simplified surge estimation',True)
code('hyd_inputs','Hydraulic hypotheses / constants table','C_vf = C["Cv_f"] / m\nC_if = C["Ci_f"]\nC_vc = C["Cv_c"] / m\nC_ic = C["Ci_c"]\nK_body = C["K_body"]',kind='given')
code('hyd_surge','Surge assembly pressure drop','A_bore = pi * d_bore**2 / 4\nV_bore = mdot_s / (rho_w * A_bore)\nDP_s = (C_vf + C_vc) * mu_w * U_s + (C_if + C_ic) * rho_w * U_s**2 + K_body * rho_w * V_bore**2 / 2',meta='unit="A_bore=mm**2, V_bore=m/s, DP_s=psi"')
code('hyd_nominal','Nominal assembly pressure drop','V_nom = mdot_n / (rho_w * A_bore)\nDP_n = (C_vf + C_vc) * mu_w * U_n + (C_if + C_ic) * rho_w * U_n**2 + K_body * rho_w * V_nom**2 / 2',meta='unit="V_nom=m/s, DP_n=psi"')
text('fit','10 / Fit strategy',True,body='[insert text here]\n\nFine media: Dutch twill. Cv and Ci remain assumed until fitted to the selected finished cloth.')
text('fit_formula','Fit the supplied model',body='[insert text here]\n\n$Delta p/(mu U) = C_v + C_i (rho U/mu)$')
text('dirt','11 / Loaded pressure drop')
text('cakemodel','Series-cake equation',body='[insert text here]\n\n$ Delta p_l = C_v mu U + C_i rho U^2 + mu U alpha_c m_d / A_f $')
code('cakeinputs','Cake inputs / constants table','alpha_c = C["alpha_c"] * m / kg\nm_d = C["dirt_mass"] * g',kind='given')
code('loaded','Loaded assembly pressure drop','DP_loaded_n = DP_n + mu_w * U_n * alpha_c * m_d / A_face\nDP_loaded_s = DP_s + mu_w * U_s * alpha_c * m_d / A_face',meta='unit=psi')
text('pressure','12 / Housing pressure screening',True)
code('pressinput','Pressure and weld-rim section','p_meop = C["p_meop"] * psi\np_proof = C["p_proof"] * psi\np_burst = C["p_burst"] * psi\nr_i = C["pocket_d"] / 2 * mm\nr_o = C["body_d"] / 2 * mm\nS_y = C["Sy"] * MPa\nS_u = C["Su"] * MPa',kind='given',meta='unit="p_meop=MPa, p_proof=MPa, p_burst=MPa"')
code('lame','Closed-end thick-cylinder check at the weld rim','sigma_h = p_burst * (r_o**2 + r_i**2) / (r_o**2 - r_i**2)\nsigma_z = p_burst * r_i**2 / (r_o**2 - r_i**2)\nsigma_r = -p_burst\nsigma_vm = (((sigma_h-sigma_z)**2 + (sigma_z-sigma_r)**2 + (sigma_r-sigma_h)**2) / 2)**0.5',meta='unit="sigma_h=MPa, sigma_z=MPa, sigma_r=MPa, sigma_vm=MPa" precision=2')
text('detail','Detail B',True)
figure('detail_b','Housing and pack / section detail','detail_circles.svg',175,90,caption='Circular sections from Build123d. Gold: solid frame; blue: media envelopes. Representative frame coining from the constants table; not a deformation prediction or verified seal.')
text('mass','22 / Full mass calculations',True)
code('mass_inputs','Density, sheet and cloth inputs / constants table','V_half = CAD["housing_volume_mm3"] * mm**3\nrho_ti = C["rho_ti"] * kg / m**3\nrho_ss = C["rho_ss"] * kg / m**3\nd_pack = C["frame_d"] * mm\nt_frame = C["frame_raw_t"] * mm\nw_coarse = C["coarse_areal_mass"] * kg / m**2\nw_fine = C["fine_areal_mass"] * kg / m**2\ngrowth = C["growth_factor"]\nm_limit = C["mass_limit"] * lb',kind='given')
code('part_mass','Housing, frames and mesh masses','A_pack = pi * d_pack**2 / 4\nV_frame = pi * (d_pack**2 - d_face**2) * t_frame / 4\nm_housings = 2 * V_half * rho_ti\nm_frames = 2 * V_frame * rho_ss\nm_coarse = 2 * A_pack * w_coarse\nm_fine = A_pack * w_fine',meta='unit="A_pack=mm**2, V_frame=mm**3, m_housings=g, m_frames=g, m_coarse=g, m_fine=g"')
code('mass_calc','Dry finished mass with a development reserve','m_dry = m_housings + m_frames + m_coarse + m_fine\nm_reserve = growth * m_dry\nMS_mass = m_limit / m_reserve - 1',meta='unit="m_dry=lb, m_reserve=lb"')
text('mass_scope','Mass scope')
text('references_intro','24 / References',True)
code('references','References','refs = Sources(**{key: Source(**value) for key, value in SOURCE_DATA.items()})',kind='sources')
(ROOT/'doc.py').write_text('\n'.join(parts),encoding='utf-8')
print(f'Authored {len(parts)-1} simple-filter blocks')
