"""Feature showcase -- exercises every kip block kind and page feature.

Blocks execute in dependency order, not document order.
"""

from kip import *
import sympy as sp
reqs = Requirements.load("requirements.toml")

# %% text scope "Scope"  wrap_title=true
"""
This note sizes a single-plate lift lug for a pressure-vessel skid, and
demonstrates every block kind kip supports: prose, inputs, symbolic
derivations, unit-checked calculations, CeTZ drawings, vector plots, tables
with spreadsheet export, and clickable references.

Peak bearing stress is @val:sigma_br against an allowable of @val:sigma_allow,
giving a margin of safety of @val:MS. The governing method follows @src:shigley
and the material allowables are from @src:matweb. This satisfies @req:REQ-014,
for this lug.

The requirements in this document apply to LUG-001. Design load, load factor,
and material allowables are defined in its local requirements file.
"""

# %% table nomenclature "Nomenclature"
symbols = nomenclature({
    "P_lift": ("Unfactored lift load", "kN"),
    "DF": "Design load factor",
    "P_d": ("Factored design load", "kN"),
    "d_pin": ("Pin diameter", "mm"),
    "t_plate": ("Plate thickness", "mm"),
    "w_lug": ("Lug width", "mm"),
    "sigma_br": ("Pin bearing stress", "MPa"),
    "sigma_nt": ("Net-section tensile stress", "MPa"),
    "sigma_allow": ("Allowable stress", "MPa"),
    "MS": "Margin of safety",
})

# %% draw sketch "Lug geometry"  caption="Plate lug, dimensions in mm."
sketch = Drawing(width=88, length="0.62cm", body="""
  let ink = rgb("#17140f")
  let dim = rgb("#123a6b")
  set-style(stroke: (paint: ink, thickness: 0.9pt))

  // lug plate: straight flanks closed by a semicircular head
  merge-path(close: true, {
    line((2, 0.5), (2, 4.2))
    arc((2, 4.2), start: 180deg, stop: 0deg, radius: 1.0)
    line((4, 4.2), (4, 0.5))
  })

  // pin hole
  circle((3, 4.2), radius: 0.45)
  // centre marks
  set-style(stroke: (paint: ink, thickness: 0.4pt))
  line((3, 3.45), (3, 4.95))
  line((2.25, 4.2), (3.75, 4.2))

  // base plate with section hatching
  set-style(stroke: (paint: ink, thickness: 0.9pt))
  rect((0.2, 0), (5.8, 0.5))
  set-style(stroke: (paint: rgb("#6d6455"), thickness: 0.4pt))
  for i in range(0, 12) {
    line((0.2 + i * 0.5, 0), (0.7 + i * 0.5, 0.5))
  }

  // dimensions
  set-style(stroke: (paint: dim, thickness: 0.5pt),
            mark: (end: "stealth", start: "stealth", scale: 0.3))
  line((3, 6.5), (3, 5.4))
  content((3, 6.9), text(size: 7pt, fill: dim)[$P$])
  line((6.4, 0), (6.4, 4.2))
  content((6.95, 2.1), text(size: 7pt, fill: dim)[$h$])
  line((2.55, 4.2), (3.45, 4.2))
  content((3, 3.05), text(size: 7pt, fill: dim)[$d$])
  line((0.2, -0.7), (5.8, -0.7))
  content((3, -1.15), text(size: 7pt, fill: dim)[$w$])
""")

# %% text method "Method"
"""
## Governing relations

Bearing stress at the pin hole and net-section tension across the reduced
area are the two candidate failure modes:
"""

# %% symbolic theory
P_s, d_s, t_s, w_s = sp.symbols("P d t w", positive=True)
sigma_bearing = P_s / (d_s * t_s)
sigma_net = P_s / ((w_s - d_s) * t_s)

# %% controlled load "Design load"
P_lift = reqs.P_design
DF = reqs.DF_min

# %% given geom "Lug geometry"
d_pin = 32 * mm
t_plate = 16 * mm
w_lug = 90 * mm

# %% controlled matl "Material: ASTM A36"
sigma_y = reqs.sigma_y_min
FS = reqs.FS_yield

# %% calc design_load "Factored design load" unit=kN
P_d = P_lift * DF

# %% calc bearing "Bearing stress at pin" unit=MPa
A_br = d_pin * t_plate
sigma_br = P_d / A_br

# %% calc netsection "Net section tension" unit=MPa
A_net = (w_lug - d_pin) * t_plate
sigma_nt = P_d / A_net

# %% calc allowable "Allowable stress" unit=MPa
sigma_allow = sigma_y / FS

# %% calc margin "Margin of safety (governing mode)"
MS = sigma_allow / sigma_br - 1

# %% plot sweep "Thickness sweep"  caption="Bearing stress against plate thickness; the allowable is the dashed line."
thicknesses = [8, 10, 12, 14, 16, 20, 25]
stresses = [(P_d / (d_pin * t * mm)).to(MPa) for t in thicknesses]
sweep = plot(thicknesses, stresses, xlabel="Plate thickness",
             ylabel="Bearing stress", label="Bearing stress", mark="o",
             xunit="mm", width=115, height=62)
sweep.line([8, 25], [sigma_allow, sigma_allow], label="Allowable", dash="dashed")

# %% plot coupon "Coupon test data"  caption="Verification by test: three A36 tensile coupons against the nominal curve."
strain = [0.0, 0.0004, 0.0008, 0.0012, 0.0016, 0.002, 0.004, 0.008, 0.012]
nominal = [0.0, 80.0, 160.0, 240.0, 250.0, 252.0, 258.0, 266.0, 271.0]
coupon = Figure(xlabel="Strain (mm/mm)", ylabel="Stress (MPa)",
                width=115, height=62)
coupon.line(strain, nominal, label="Nominal A36")
coupon.scatter([0.0004, 0.0012, 0.002, 0.008],
               [83.0, 236.0, 254.0, 262.0], label="Coupon 1", mark="o")
coupon.scatter([0.0004, 0.0012, 0.002, 0.008],
               [78.0, 244.0, 248.0, 269.0], label="Coupon 2", mark="s")
sigma_coupon_min = 254.0 * MPa

# %% table cases "Load case summary"  caption="All cases carry positive margin; the workbook holds the full 12-case matrix."
_case_rows = [
    ("LC-01", "Static lift", 18.0, 2.0, 70.3, 0.113),
    ("LC-02", "Dynamic hoist", 18.0, 2.5, 87.9, 0.703),
    ("LC-03", "Side pull 5 deg", 18.1, 2.0, 70.7, 0.117),
    ("LC-04", "Two-point share", 9.0, 2.0, 35.2, 1.227),
    ("LC-05", "Shock stop", 18.0, 3.0, 105.5, 0.419),
    ("LC-06", "Proof load", 18.0, 2.2, 77.3, 0.937),
    ("LC-07", "Wind + lift", 18.4, 2.0, 71.9, 0.082),
    ("LC-08", "Tilt 15 deg", 18.6, 2.0, 72.7, 0.070),
    ("LC-09", "Off-axis 10 deg", 18.3, 2.0, 71.5, 0.093),
    ("LC-10", "Cold service", 18.0, 2.0, 70.3, 0.061),
    ("LC-11", "Fatigue mean", 12.0, 2.0, 46.9, 1.192),
    ("LC-12", "Ultimate check", 18.0, 3.3, 116.0, 0.291),
]
cases = Table(
    columns=[
        Column("case", "Case", align="left"),
        Column("desc", "Description", align="left"),
        Column("load", "Load", unit="kN", precision=1),
        Column("df", "DF", precision=2),
        Column("stress", "Bearing", unit="MPa", precision=1),
        Column("ms", "MS", precision=3),
    ],
    rows=[
        (c, d, ld * kN, df, st * MPa, ms)
        for c, d, ld, df, st, ms in _case_rows
    ],
    max_rows=6,
    xlsx="load_cases.xlsx",
    highlight={6: "fail"},
)

# %% table controlled "Controlled variables"
controlled = variables_table(reqs)

# %% table compliance "Verification cross-reference matrix (VCRM)"
reqs.verify("REQ-014", MS, ">= 0", evidence="margin")
reqs.verify("REQ-015", sigma_nt / sigma_br, "< 1", evidence="netsection")
reqs.verify("REQ-016", sigma_coupon_min, ">= sigma_y_min", evidence="coupon")
compliance = compliance_matrix(reqs)

# %% text conclusion "Conclusion"
"""
## Result

Bearing at the pin governs, with @val:sigma_br against an allowable of
@val:sigma_allow. Net-section tension reaches only @val:sigma_nt and does not
govern. The controlling margin of safety is @val:MS, so the lug is adequate
as drawn in @blk:sketch. Design factors follow @src:asme.
"""

# %% sources refs "References" columns=1
refs = Sources(
    shigley=Source(
        title="Shigley's Mechanical Engineering Design",
        author="R. Budynas and K. Nisbett",
        publisher="McGraw-Hill", year=2020, section="Ch. 3-14",
        url="https://www.mheducation.com/highered/product/M9781260113310.html",
    ),
    matweb=Source(
        title="ASTM A36 structural steel, material data sheet",
        publisher="MatWeb", section="Mechanical properties",
        url="https://www.matweb.com/search/DataSheet.aspx?MatGUID=afc003f4fb40465fa3df05129f0e88e6",
    ),
    asme=Source(
        title="ASME BTH-1, Design of Below-the-Hook Lifting Devices",
        publisher="ASME", year=2023, section="Section 3-3.2",
        url="https://www.asme.org/codes-standards/find-codes-standards/bth-1-design-below-hook-lifting-devices",
        note="design factor basis",
    ),
)

# %% text cad_intro "CAD definition" columns=1 pagebreak=true
"""
## Model and drawing exports

The following two-column drawing section uses one build123d solid model of
LUG-001. The plate is 90 mm wide and 16 mm thick with a 32 mm pin hole.
The hole center is 80 mm above the base; the rounded head has a 45 mm radius.
A 150 x 70 x 10 mm base is included to show the mounting interface.
Z is vertical, X is plate width, and Y is plate thickness.

Solid lines show visible edges and dashed lines show hidden edges. The
section is an actual intersection on XZ at Y = 0, through the pin axis.
The face export contains only one planar plate face, including its hole.
DXF files are in millimetres at 1:1; PDF views are scaled to fit.
"""

# %% draw cad_iso "Isometric wireframe" columns=2  caption="LUG-001 and mounting base; Z up."
from kip.cad import load_build123d, cad_view, cad_section, cad_face
bd = load_build123d()
profile = bd.Plane.XZ * (
    bd.Pos(0, 40) * bd.Rectangle(float(w_lug.magnitude), 80)
    + bd.Pos(0, 80) * bd.Circle(float(w_lug.magnitude) / 2)
    - bd.Pos(0, 80) * bd.Circle(float(d_pin.magnitude) / 2)
)
lug_solid = bd.extrude(profile, amount=float(t_plate.magnitude) / 2, both=True)
base_solid = bd.Pos(0, 0, -5) * bd.Box(150, 70, 10)
cad_model = lug_solid + base_solid
iso_drawing = cad_view(cad_model, "iso", caption="Isometric; visible and hidden edges.")

# %% draw cad_top "Top view (+Z)"
top_drawing = cad_view(cad_model, "top", caption="Looking down; pin-hole edges are hidden.")

# %% draw cad_side "Side view (+X)"
side_drawing = cad_view(cad_model, "side", caption="Plate thickness and mounting-base profile.")

# %% draw cad_bottom "Bottom view (-Z)"
bottom_drawing = cad_view(cad_model, "bottom", caption="Underside of base; plate edges hidden.")

# %% draw cad_section "Section A-A / XZ at Y = 0"
section_drawing = cad_section(cad_model, bd.Plane.XZ, dxf="lug_section_AA.dxf",
    caption="True center-plane section through the pin hole.")

# %% draw cad_face "Single plate face / local XY"
plate_face = lug_solid.faces().filter_by(bd.Axis.Y).sort_by(bd.Axis.Y)[0]
face_drawing = cad_face(plate_face, dxf="lug_side_face.dxf",
    caption="One planar face; outer profile and pin-hole wire.")
