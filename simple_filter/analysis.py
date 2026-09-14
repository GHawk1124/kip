"""Editable inputs and hand calculations. No FEA or Monte Carlo runs."""
from pathlib import Path
import math
import json
from kip import *

ROOT = Path(__file__).resolve().parent
ROWS = read_records(ROOT / "input/constants.xlsx")
C = {row["key"]: float(row["value"]) for row in ROWS}
if len(C) != len(ROWS) or not all(math.isfinite(v) for v in C.values()):
    raise ValueError("Constants must have unique keys and finite numeric values")

EXPECTED_UNITS={'temperature_F': 'degF', 'rho_w': 'kg/m3', 'mu_w': 'Pa s', 'mdot_n': 'lb/s', 'mdot_s': 'lb/s', 'p_meop': 'psi', 'p_proof': 'psi', 'p_burst': 'psi', 'dp_clean_limit': 'psi', 'dp_loaded_limit': 'psi', 'dirt_mass': 'g', 'mass_limit': 'lb', 'rating': 'um', 'efficiency': 'percent', 'efficiency_size': 'um', 'active_d': 'mm', 'frame_d': 'mm', 'frame_raw_t': 'mm', 'frame_assembled_t': 'mm', 'coarse_t': 'mm', 'fine_t': 'mm', 'body_d': 'mm', 'pocket_d': 'mm', 'outer_shoulder_z': 'mm', 'inner_shoulder_z': 'mm', 'stub_start_z': 'mm', 'half_length': 'mm', 'stub_od': 'mm', 'stub_id': 'mm', 'Cv_f': '1/m', 'Ci_f': '1', 'Cv_c': '1/m', 'Ci_c': '1', 'K_body': '1', 'alpha_c': 'm/kg', 'rho_ti': 'kg/m3', 'rho_ss': 'kg/m3', 'Sy': 'MPa', 'Su': 'MPa', 'coarse_areal_mass': 'kg/m2', 'fine_areal_mass': 'kg/m2', 'growth_factor': '1'}
for row in ROWS:
    if row["key"] in EXPECTED_UNITS and row["unit"] != EXPECTED_UNITS[row["key"]]:
        raise ValueError(f"Use {EXPECTED_UNITS[row['key']]} for {row['key']}")

# 08 — Water properties and approach velocity
@calculation(units={"A_face":"mm**2", "U_n":"m/s", "U_s":"m/s"})
def flow(c):
    rho_w = c["rho_w"] * kg / m**3
    mu_w = c["mu_w"] * Pa * s
    d_face = c["active_d"] * mm
    mdot_n = c["mdot_n"] * lb / s
    mdot_s = c["mdot_s"] * lb / s
    # equations
    A_face = pi * d_face**2 / 4
    U_n = mdot_n / (rho_w * A_face)
    U_s = mdot_s / (rho_w * A_face)
    return locals()


# 09 — Same assumed resistance model for nominal and surge flow
@calculation(units={"A_bore":"mm**2", "V_bore":"m/s", "U":"m/s", "DP":"psi"})
def clean(c, water, mdot):
    rho_w, mu_w, A_face = water.rho_w, water.mu_w, water.A_face
    d_bore = c["stub_id"] * mm
    C_vf, C_if = c["Cv_f"] / m, c["Ci_f"]
    C_vc, C_ic = c["Cv_c"] / m, c["Ci_c"]
    K_body = c["K_body"]
    # equations
    A_bore = pi * d_bore**2 / 4
    V_bore = mdot / (rho_w * A_bore)
    U = mdot / (rho_w * A_face)
    DP = (C_vf + C_vc) * mu_w * U + (C_if + C_ic) * rho_w * U**2 + K_body * rho_w * V_bore**2 / 2
    return locals()


# 11 — Cake resistance at retained dirt capacity
@calculation(units={"DP_loaded_n":"psi", "DP_loaded_s":"psi"})
def loaded(c, water, nominal, surge):
    mu_w, A_face = water.mu_w, water.A_face
    U_n, U_s = water.U_n, water.U_s
    DP_n, DP_s = nominal.DP, surge.DP
    alpha_c = c["alpha_c"] * m / kg
    m_d = c["dirt_mass"] * g
    # equations
    DP_loaded_n = DP_n + mu_w * U_n * alpha_c * m_d / A_face
    DP_loaded_s = DP_s + mu_w * U_s * alpha_c * m_d / A_face
    return locals()


# 12 — Local cylinder screen, not a burst qualification
@calculation(units={"sigma_h":"MPa", "sigma_z":"MPa", "sigma_r":"MPa", "sigma_vm":"MPa"}, precision=2)
def pressure(c):
    p_burst = (c["p_burst"] * psi).to(MPa)
    r_i = c["pocket_d"] / 2 * mm
    r_o = c["body_d"] / 2 * mm
    # equations
    sigma_h = p_burst * (r_o**2 + r_i**2) / (r_o**2 - r_i**2)
    sigma_z = p_burst * r_i**2 / (r_o**2 - r_i**2)
    sigma_r = -p_burst
    sigma_vm = (((sigma_h-sigma_z)**2 + (sigma_z-sigma_r)**2 + (sigma_r-sigma_h)**2) / 2)**0.5
    return locals()


# 22 — Actual CAD housing volume; mesh mass uses areal weight, not solid discs
@calculation(units={"A_pack":"mm**2", "V_frame":"mm**3", "m_housings":"g", "m_frames":"g", "m_coarse":"g", "m_fine":"g", "m_dry":"lb", "m_reserve":"lb"})
def mass(c, housing_volume_mm3):
    V_half = housing_volume_mm3 * mm**3
    rho_ti, rho_ss = c["rho_ti"] * kg / m**3, c["rho_ss"] * kg / m**3
    d_pack, d_face = c["frame_d"] * mm, c["active_d"] * mm
    t_frame = c["frame_raw_t"] * mm
    w_coarse = c["coarse_areal_mass"] * kg / m**2
    w_fine = c["fine_areal_mass"] * kg / m**2
    growth, m_limit = c["growth_factor"], c["mass_limit"] * lb
    # equations
    A_pack = pi * d_pack**2 / 4
    V_frame = pi * (d_pack**2 - d_face**2) * t_frame / 4
    m_housings = 2 * V_half * rho_ti
    m_frames = 2 * V_frame * rho_ss
    m_coarse = 2 * A_pack * w_coarse
    m_fine = A_pack * w_fine
    m_dry = m_housings + m_frames + m_coarse + m_fine
    m_reserve = growth * m_dry
    MS_mass = m_limit / m_reserve - 1
    return locals()


def save_results(**calculations):
    """Machine-readable copy of the same quantities shown in the PDF."""
    results = {}
    for section, result in calculations.items():
        results[section] = {
            key: {"value": float(value.magnitude), "unit": str(value.units)}
            for key, value in result.values.items()
            if hasattr(value, "magnitude") and hasattr(value, "units")
        }
    (ROOT / "output/calculations.json").write_text(json.dumps(results, indent=2))
