"""Unit-checked filter models. Numeric inputs live in input/design.xlsx."""
from pathlib import Path
import csv
import math
import tomllib

import numpy as np
from kip import Constants, Sheet, Table, Column, Figure, calculation, mm, m, kg, s, Pa, psi, MPa, lb, um, pi
from kip.packet import UnavailableInput
from kip.sheets import parse_unit

ROOT = Path(__file__).resolve().parent
BOOK = ROOT / "input/design.xlsx"


def sheet(name):
    try:
        return Sheet.load(BOOK, name)
    except (FileNotFoundError, KeyError) as exc:
        raise UnavailableInput(f"Missing input/design.xlsx / {name}.") from exc
    except ValueError as exc:
        if "has no rows" in str(exc):
            raise UnavailableInput(f"{name} has no rows yet.") from exc
        raise


def sweep(driver):
    values = [float(r["value"]) * parse_unit(r["unit"]) for r in sheet("Sweeps") if r["driver"] == driver]
    if not values:
        raise UnavailableInput(f"Sweeps: no values supplied for {driver}.")
    return values


def positive(value, unit, name, *, zero=False):
    number = float(value.to(unit).magnitude)
    if not math.isfinite(number) or (number < 0 if zero else number <= 0):
        raise ValueError(f"{name} must be finite and {'nonnegative' if zero else 'positive'}")
    return value


def bore(od, wall):
    positive(od, m, "Inlet OD")
    positive(wall, m, "Inlet wall")
    return positive(od - 2 * wall, m, "Inlet ID (OD - 2 wall)")


def area(diameter):
    return pi * positive(diameter, m, "Diameter")**2 / 4


def velocity(mdot, rho, face):
    return positive(mdot, kg/s, "Mass flow", zero=True) / (positive(rho, kg/m**3, "Density") * positive(face, m**2, "Area"))


def clean_drop(mdot, rho, mu, face, Cv, Ci, blockage=0):
    """Single clean screen or calibrated finished pack, using exposed face area."""
    if not 0 <= blockage < 1:
        raise ValueError("Blocked-area fraction must be in [0, 1)")
    U = velocity(mdot, rho, face) / (1 - blockage)
    positive(mu, Pa*s, "Viscosity")
    positive(Cv, 1/m, "Cv", zero=True)
    positive(Ci, "", "Ci", zero=True)
    return (Cv * mu * U + Ci * rho * U**2).to(psi)


def cake_drop(mdot, c, Cv, Ci, alpha):
    positive(alpha, m/kg, "Specific cake resistance", zero=True)
    positive(c.dirt_mass, kg, "Retained dirt mass", zero=True)
    face = area(c.active_d)
    return clean_drop(mdot, c.rho, c.mu, face, Cv, Ci) + (c.mu * velocity(mdot, c.rho, face) * alpha * c.dirt_mass / face).to(psi)


def dynamic_pressure(mdot, c, od=None, wall=None):
    d = bore(c.stub_od if od is None else od, c.stub_wall if wall is None else wall)
    V = velocity(mdot, c.rho, area(d))
    return (c.rho * V**2 / 2).to(psi)


def cylinder_vm(p, od, id):
    positive(p, Pa, "Pressure", zero=True)
    if not 0 < id.to(m).magnitude < od.to(m).magnitude:
        raise ValueError("Cylinder requires 0 < ID < OD")
    return (math.sqrt(3) * p * od**2 / (od**2 - id**2)).to(MPa)


def reference_coefficients(row):
    Da, L = float(row["da_um"]) * um, float(row["l_mm"]) * mm
    positive(Da, m, "Average capillary diameter")
    positive(L, m, "Cloth thickness")
    A1, A2 = float(row["a1"]), float(row["a2"])
    if A1 <= 0 or A2 < 0 or not all(map(math.isfinite, (A1, A2))):
        raise ValueError("Reference coefficients must be finite, with A1 > 0 and A2 >= 0")
    return (A1 * L / Da**2).to(1/m), (A2 * L / Da).to("")


def calibrated(row):
    """A missing or partial coefficient pair never becomes zero resistance."""
    if row.get("cv_per_m") in (None, "") or row.get("ci") in (None, ""):
        return None
    if not str(row.get("evidence", "")).strip() or str(row["evidence"]).upper().startswith("OPEN"):
        return None
    Cv, Ci = float(row["cv_per_m"]) / m, float(row["ci"]) * parse_unit("")
    positive(Cv, 1/m, "Calibrated Cv", zero=True)
    positive(Ci, "", "Calibrated Ci", zero=True)
    if Cv.magnitude == 0 and Ci.magnitude == 0:
        raise ValueError("A calibrated pack cannot have two zero resistance coefficients")
    return Cv, Ci


def fit_coefficients(flows, drops, rho, mu, face):
    """Fit pressure data in SI, returning Cv [1/m] and Ci [1]. No implicit scope."""
    positive(mu, Pa*s, "Viscosity")
    U = np.array([velocity(q, rho, face).to(m/s).magnitude for q in flows])
    y = np.array([positive(p, Pa, "Measured drop", zero=True).to(Pa).magnitude for p in drops])
    if len(U) != len(y) or len(U) < 3:
        raise ValueError("Provide at least three paired flow / pressure measurements")
    X = np.column_stack([mu.to(Pa*s).magnitude * U, rho.to(kg/m**3).magnitude * U**2])
    scale = np.linalg.norm(X, axis=0)
    if np.any(scale == 0) or np.linalg.matrix_rank(X / scale) < 2:
        raise ValueError("Calibration needs distinct nonzero velocities")
    result = np.linalg.lstsq(X / scale, y, rcond=None)[0] / scale
    if np.any(result < 0):
        raise ValueError("Fit gives a negative resistance term; review data, range and model")
    return result[0] / m, result[1] * parse_unit("")


@calculation
def flow(c):
    d_o, t = c.stub_od, c.stub_wall
    d_face, rho = c.active_d, c.rho
    mdot_n, mdot_s = c.mdot_n, c.mdot_s
    bore(d_o, t)
    positive(rho, kg/m**3, "Density")
    # equations
    d_i = d_o - 2 * t                         # -> inch
    A_face = pi * d_face**2 / 4               # -> mm^2
    U_n = mdot_n / (rho * A_face)             # -> m/s
    U_s = mdot_s / (rho * A_face)             # -> m/s


def profile(c):
    d = {key: c.value(key, mm) for key in (
        "body_d", "pocket_d", "active_d", "outer_shoulder_z", "inner_shoulder_z",
        "stub_start_z", "half_length", "stub_od", "fine_t", "coarse_t", "frame_assembled_t")}
    ri = bore(c.stub_od, c.stub_wall).to(mm).magnitude / 2
    land = d["fine_t"] / 2 + d["coarse_t"] + d["frame_assembled_t"]
    if not (d["body_d"] > d["pocket_d"] > c.value("frame_d", mm) > d["active_d"] > 2*ri
            and d["half_length"] > d["stub_start_z"] > d["inner_shoulder_z"] > land):
        raise ValueError("Housing / media dimensions do not form a valid nested stack")
    return [(d["body_d"]/2, 0), (d["body_d"]/2, d["outer_shoulder_z"]),
            (d["stub_od"]/2, d["stub_start_z"]), (d["stub_od"]/2, d["half_length"]),
            (ri, d["half_length"]), (ri, d["stub_start_z"]),
            (d["active_d"]/2, d["inner_shoulder_z"]), (d["active_d"]/2, land),
            (d["pocket_d"]/2, land), (d["pocket_d"]/2, 0)]


def housing_volume(c):
    points = profile(c)
    volume = abs(sum((z2-z1)*(r1*r1+r1*r2+r2*r2) for (r1,z1),(r2,z2)
                     in zip(points, points[1:]+points[:1]))) * pi/3
    return volume * mm**3


def mass(c):
    housings = 2 * housing_volume(c) * c.rho_ti
    frames = 2 * (area(c.frame_d) - area(c.active_d)) * c.frame_raw_t * c.rho_ss
    cloth = area(c.frame_d) * (2*c.coarse_areal_mass + c.fine_areal_mass)
    return (housings + frames + cloth).to(lb)


def plain(headers, rows):
    return Table([Column(str(i), title, align="left") for i,title in enumerate(headers)], rows, zebra=False)


def inputs_table(c):
    pairs = [("Inlet / outlet OD", "stub_od"), ("Wall", "stub_wall"), ("Filtration rating", "rating"),
             ("MEOP", "p_meop"), ("Proof", "p_proof"), ("Burst", "p_burst"),
             ("Nominal flow", "mdot_n"), ("Surge flow", "mdot_s"),
             ("Density", "rho"), ("Dynamic viscosity", "mu"), ("Temperature", "temperature_F")]
    return plain(["Input", "Value", "Workbook key"], [(label, c[key], key) for label,key in pairs])


def fluid_note(c):
    data = tomllib.loads((ROOT / "fluid.toml").read_text(encoding="utf-8"))
    return (f"Selected fluid: {data['name']} ({data['phase']}). {data['property_basis']} "
            "Use density and viscosity at the selected temperature and pressure. "
            "This is a single-phase, constant-property model; significant gas density change, "
            "two-phase flow and non-Newtonian behavior need a different flow model. "
            "Fluid / material compatibility remains OPEN.")


def requirements_table(reqs, c):
    targets = {"F-01": c.text("p_meop"), "F-02": c.text("p_proof"), "F-03": c.text("p_burst"),
        "F-04": c.format("{rating}; {efficiency} at {efficiency_size}"),
        "F-05": c.format("{dp_clean_limit} at {mdot_n}; surge {mdot_s}"),
        "F-06": c.format("{dirt_mass}; {dp_loaded_limit} at {mdot_n}"),
        "F-07": c.text("mass_limit"), "F-08": "Selected fluid and state", "F-09": "OPEN", "F-10": "7 parts"}
    return plain(["ID", "Requirement", "Target"], [(r.id, r.text, targets[r.id]) for r in reqs.all_requirements().values()])


def inlet_table(c):
    d = bore(c.stub_od, c.stub_wall)
    return plain(["Flow", "Bore velocity", "Dynamic pressure"], [
        (name, velocity(q,c.rho,area(d)).to(m/s), dynamic_pressure(q,c)) for name,q in (("Nominal",c.mdot_n),("Surge",c.mdot_s))])


def flow_table(c):
    result = flow(c)
    return plain(["Quantity", "Value"], [("Derived bore",result.d_i.to("inch")),
        ("Exposed face area",result.A_face.to(mm**2)),("Nominal approach velocity",result.U_n.to(m/s)),
        ("Surge approach velocity",result.U_s.to(m/s))])


def inlet_loss_table(c):
    return plain(["Assumed K", "Nominal loss", "Surge loss"],
        [(K,positive(K,"","Inlet K",zero=True)*dynamic_pressure(c.mdot_n,c),K*dynamic_pressure(c.mdot_s,c))
         for K in sweep("inlet_K")])


def pressure_table(c):
    rows = []
    for name,od,id in (("Stub",c.stub_od,bore(c.stub_od,c.stub_wall)),("Weld rim",c.body_d,c.pocket_d)):
        for case,p,strength in (("Proof",c.p_proof,c.Sy),("Burst",c.p_burst,c.Su)):
            stress = cylinder_vm(p,od,id)
            rows.append((name+" / "+case,stress,(strength/stress).to("").magnitude))
    return plain(["Location / case", "VM stress", "Strength / stress"], rows)


def mass_table(c):
    estimate = mass(c)
    return plain(["Quantity", "Value"], [("Estimated dry mass",estimate),("With growth allowance",estimate*c.growth_factor),
        ("Mass limit",c.mass_limit)])


def bom(c):
    return plain(["Component", "Qty", "Material / definition"], [
        ("Turned cup",2,"CP Ti Grade 2; identical halves with integral stubs"),
        ("Annular frame",2,c.format("316L; raw {frame_raw_t}, assembled {frame_assembled_t}")),
        ("Coarse support",2,c.format("316 stainless, 40 x 40; assembled {coarse_t}")),
        ("Fine cloth",1,c.format("316 stainless Dutch twill; {rating}; thickness {fine_t} provisional"))])


def reference_table(c):
    return plain(["Cloth", "Da (µm)", "L (mm)", "A1", "A2"],
        [(r["screen"],r["da_um"],f"{r['l_mm']:.5f}",r["a1"],r["a2"]) for r in sheet("ReferenceScreens")])


def rating_table(c):
    rows = []
    for r in sheet("Calibration"):
        pair = calibrated(r)
        value = clean_drop(c.mdot_n,c.rho,c.mu,area(c.active_d),*pair) if pair else "OPEN"
        rows.append((float(r["rating_um"])*um, value, "Data supplied" if pair else "Cv / Ci and evidence missing"))
    return plain(["Rating", "Nominal pack loss", "Calibration"], rows)


def selected_table(c):
    selected = [r for r in sheet("Calibration") if math.isclose(float(r["rating_um"]),c.value("rating",um))]
    if len(selected) > 1:
        raise ValueError("Duplicate calibration rows for the selected rating")
    pair = calibrated(selected[0]) if selected else None
    if not pair:
        raise UnavailableInput("Selected rating: finished-pack Cv, Ci and supporting evidence are OPEN. Reference sweeps remain available.")
    return plain(["Case", "Clean pack loss"], [(name,clean_drop(q,c.rho,c.mu,area(c.active_d),*pair))
        for name,q in (("Nominal",c.mdot_n),("Surge",c.mdot_s))])


def figure(xlabel, ylabel):
    return Figure(xlabel=xlabel, ylabel=ylabel, width=80, height=64)


def flow_plot(c):
    xs = sorted({q.to(lb/s).magnitude for q in [*sweep("mass_flow"),c.mdot_n,c.mdot_s]})
    xs = [q*lb/s for q in xs]
    fig = figure("Mass flow (lb/s)", "Screen loss (psi)")
    for r in sheet("ReferenceScreens"):
        ys = [clean_drop(q,c.rho,c.mu,area(c.active_d),*reference_coefficients(r)) for q in xs]
        fig.line(xs,ys,label=r["screen"],xunit="lb/s",yunit="psi")
    return fig


def inlet_plot(c, driver):
    xs = sweep(driver)
    K = max(v.to("").magnitude for v in sweep("inlet_K"))
    if K < 0:
        raise ValueError("Inlet K must be nonnegative")
    fig = figure(("OD" if driver == "stub_od" else "Wall")+" (in)", "Housing loss (psi)")
    for name,q in (("Nominal",c.mdot_n),("Surge",c.mdot_s)):
        ys = [K * dynamic_pressure(q,c,**{("od" if driver == "stub_od" else "wall"):v}) for v in xs]
        fig.line(xs,ys,label=f"{name}, K={K:g}",xunit="inch",yunit="psi",mark="o")
    return fig


def pressure_plot(c):
    xs = sweep("pressure_factor")
    fig = figure("Specified pressure multiplier", "VM stress / strength")
    for name,od,id in (("Stub",c.stub_od,bore(c.stub_od,c.stub_wall)),("Rim",c.body_d,c.pocket_d)):
        for case,p,strength in (("proof",c.p_proof,c.Sy),("burst",c.p_burst,c.Su)):
            fig.line(xs,[(cylinder_vm(p*f,od,id)/strength).to("").magnitude for f in xs],label=f"{name} {case}")
    fig.line(xs,[1]*len(xs),label="Strength",dash="dashed")
    return fig


def loading_plot(c, driver):
    xs = sweep(driver)
    r = next(iter(sheet("ReferenceScreens")))
    Cv,Ci = reference_coefficients(r)
    fig = figure("Blocked face fraction" if driver == "blockage" else "Cake resistance (m/kg)", "Screen loss (psi)")
    fig.title = f"{r['screen']} only"
    for name,q in (("Nominal",c.mdot_n),("Surge",c.mdot_s)):
        ys = [clean_drop(q,c.rho,c.mu,area(c.active_d),Cv,Ci,v.to("").magnitude) if driver == "blockage"
              else cake_drop(q,c,Cv,Ci,v) for v in xs]
        fig.line(xs,ys,label=name,yunit="psi",mark="o")
    return fig


def test_table():
    return sheet("Tests").table("id","requirement","procedure","criterion", zebra=False)


def export_sweeps(c):
    """Export exactly the plotted series, plus explicit uncalibrated rating rows."""
    plots = {"mass_flow":lambda:flow_plot(c), "stub_od":lambda:inlet_plot(c,"stub_od"), "stub_wall":lambda:inlet_plot(c,"stub_wall"),
             "pressure_factor":lambda:pressure_plot(c), "blockage":lambda:loading_plot(c,"blockage"), "cake_alpha":lambda:loading_plot(c,"cake_alpha")}
    out = ROOT / "output"
    out.mkdir(exist_ok=True)
    with (out / "sweeps.csv").open("w",newline="",encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["driver","series","x","x_axis","y","y_axis","basis"])
        for driver,make_plot in plots.items():
            try:
                fig = make_plot()
            except UnavailableInput as exc:
                writer.writerow([driver,"", "", "", "OPEN", "", str(exc)])
                continue
            for series in fig.series:
                writer.writerows((driver,series.label,x,fig.xlabel,y,fig.ylabel,"Sensitivity / local screen; not qualification")
                                 for x,y in zip(series.x,series.y))
        try:
            ratings = rating_table(c).rows
        except UnavailableInput as exc:
            writer.writerow(["rating","", "", "", "OPEN", "", str(exc)])
            return
        for row in ratings:
            value = row[1].to(psi).magnitude if hasattr(row[1],"to") else row[1]
            writer.writerow(["rating","Finished pack",row[0].to(um).magnitude,"Rating (um)",value,"Nominal pack loss (psi)",row[2]])
