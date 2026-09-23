"""Physical limits, unit invariance and missing calibration in the new example."""
import importlib.util
from pathlib import Path
import sys

import numpy as np
import pytest
from kip import Constants, kg, m, mm, s, Pa, psi, inch, lb, MPa
from kip.packet import UnavailableInput

_spec = importlib.util.spec_from_file_location("filter_analysis", Path(__file__).parents[1]/"fluid_filter/analysis.py")
a = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = a
_spec.loader.exec_module(a)


@pytest.fixture
def c():
    return Constants.load(a.BOOK)


def test_inherited_requirements_and_new_bore(c):
    assert a.bore(c.stub_od,c.stub_wall).to(inch).magnitude == pytest.approx(.2)
    assert [c.value(k,psi) for k in ("p_meop","p_proof","p_burst")] == [650,1300,2600]
    assert [c.value(k,lb/s) for k in ("mdot_n","mdot_s")] == [.14,.47]
    with pytest.raises(ValueError,match="Inlet ID"):
        a.bore(.25*inch,.125*inch)


def test_reference_coefficients_and_superficial_velocity(c):
    Cv,Ci = a.reference_coefficients(next(iter(a.sheet("ReferenceScreens"))))
    assert Cv.to(1/m).magnitude == pytest.approx(190*.00014732/(22.8e-6)**2)
    assert Ci.magnitude == pytest.approx(18*.00014732/22.8e-6)
    flow = c.mdot_n.to(kg/s).magnitude
    rho,mu = c.value("rho",kg/m**3), c.value("mu",Pa*s)
    U = flow/(rho*np.pi*(.058**2)/4)
    predicted = a.clean_drop(c.mdot_n,c.rho,c.mu,a.area(c.active_d),Cv,Ci)
    assert predicted.to(Pa).magnitude == pytest.approx(Cv.magnitude*mu*U+Ci.magnitude*rho*U**2)


def test_viscous_and_inertial_limits_and_unit_invariance(c):
    face = a.area(c.active_d)
    for Cv,Ci,ratio in ((1e7/m,0*kg/kg,2),(0/m,100*kg/kg,4)):
        first = a.clean_drop(c.mdot_n,c.rho,c.mu,face,Cv,Ci)
        doubled = a.clean_drop(2*c.mdot_n,c.rho,c.mu,face,Cv,Ci)
        assert (doubled/first).magnitude == pytest.approx(ratio)
        alternate = a.clean_drop(c.mdot_n.to(kg/s),c.rho.to(lb/inch**3),c.mu,face.to(inch**2),Cv,Ci)
        assert alternate.magnitude == pytest.approx(first.magnitude)
    assert a.clean_drop(0*kg/s,c.rho,c.mu,face,1e7/m,100*kg/kg).magnitude == 0


def test_fluid_changes_recompute_fixed_mass_flow():
    base = a.clean_drop(.1*kg/s,1000*kg/m**3,.001*Pa*s,.01*m**2,1e7/m,100*kg/kg)
    dense = a.clean_drop(.1*kg/s,2000*kg/m**3,.001*Pa*s,.01*m**2,1e7/m,100*kg/kg)
    assert dense.magnitude == pytest.approx(base.magnitude/2)
    with pytest.raises(ValueError,match="Density"):
        a.clean_drop(.1*kg/s,0*kg/m**3,.001*Pa*s,.01*m**2,1e7/m,100*kg/kg)


def test_loading_is_separate_and_has_correct_limits(c):
    Cv,Ci = a.reference_coefficients(next(iter(a.sheet("ReferenceScreens"))))
    face = a.area(c.active_d)
    clean = a.clean_drop(c.mdot_n,c.rho,c.mu,face,Cv,Ci)
    assert a.cake_drop(c.mdot_n,c,Cv,Ci,0*m/kg).magnitude == pytest.approx(clean.magnitude)
    blocked = a.clean_drop(c.mdot_n,c.rho,c.mu,face,Cv,Ci,.5)
    assert 2 < (blocked/clean).magnitude < 4
    with pytest.raises(ValueError,match="Blocked-area"):
        a.clean_drop(c.mdot_n,c.rho,c.mu,face,Cv,Ci,1)


def test_calibration_stays_open_for_all_micron_ratings(c):
    assert all(a.calibrated(row) is None for row in a.sheet("Calibration"))
    assert a.calibrated({"cv_per_m":1e7,"ci":"","evidence":"Bench report"}) is None
    assert a.calibrated({"cv_per_m":1e7,"ci":20,"evidence":"OPEN"}) is None
    assert a.calibrated({"cv_per_m":1e7,"ci":20,"evidence":"Bench report"}) is not None
    with pytest.raises(UnavailableInput,match="finished-pack"):
        a.selected_table(c)


def test_fit_recovers_known_coefficients_and_rejects_singular_data(c):
    flows = [.03*kg/s,.08*kg/s,.15*kg/s,.25*kg/s]
    face = a.area(c.active_d)
    Cv,Ci = 4e7/m,300*kg/kg
    drops = [a.clean_drop(q,c.rho,c.mu,face,Cv,Ci) for q in flows]
    fitted = a.fit_coefficients(flows,drops,c.rho,c.mu,face)
    assert fitted[0].magnitude == pytest.approx(Cv.magnitude)
    assert fitted[1].magnitude == pytest.approx(Ci.magnitude)
    with pytest.raises(ValueError,match="distinct"):
        a.fit_coefficients([flows[0]]*3,[drops[0]]*3,c.rho,c.mu,face)


def test_cylinder_screen_matches_independent_lame_components(c):
    p = c.p_burst.to(Pa).magnitude
    ro,ri = c.stub_od.to(m).magnitude/2,a.bore(c.stub_od,c.stub_wall).to(m).magnitude/2
    hoop = p*(ro*ro+ri*ri)/(ro*ro-ri*ri)
    axial = p*ri*ri/(ro*ro-ri*ri)
    radial = -p
    expected = np.sqrt(((hoop-axial)**2+(axial-radial)**2+(radial-hoop)**2)/2)
    assert a.cylinder_vm(c.p_burst,c.stub_od,2*ri*m).to(Pa).magnitude == pytest.approx(expected)
    assert a.housing_volume(c).to(mm**3).magnitude > 0


def test_sweeps_contain_requested_baselines(c):
    assert any(np.isclose(x.to(inch).magnitude,.25) for x in a.sweep("stub_od"))
    assert any(np.isclose(x.to(inch).magnitude,.025) for x in a.sweep("stub_wall"))
    assert {q.to(lb/s).magnitude for q in (c.mdot_n,c.mdot_s)} <= {q.to(lb/s).magnitude for q in a.sweep("mass_flow")}
    assert any(x.magnitude == 1 for x in a.sweep("pressure_factor"))


def test_worked_calculations_match_the_screen_and_cylinder_models(c):
    water = a.flow(c)
    screen = a.reference_screen(c, water)
    Cv, Ci = a.reference_coefficients(next(r for r in a.sheet("ReferenceScreens") if r["screen"] == "200 x 1400"))
    face = a.area(c.active_d)
    assert screen.Cv.to(1/m).magnitude == pytest.approx(Cv.to(1/m).magnitude)
    assert screen.Ci.magnitude == pytest.approx(Ci.magnitude)
    assert screen.dp_n.magnitude == pytest.approx(
        a.clean_drop(c.mdot_n, c.rho, c.mu, face, Cv, Ci).magnitude)

    bore = a.bore_flow(c, water)
    assert bore.q_n.magnitude == pytest.approx(a.dynamic_pressure(c.mdot_n, c).magnitude)
    assert bore.q_s.magnitude == pytest.approx(a.dynamic_pressure(c.mdot_s, c).magnitude)

    housing = a.housing_loss(c, bore)
    assert housing.dp_housing_n.magnitude == pytest.approx(bore.q_n.magnitude)
    blocked = a.blocked_drop(c, water, screen)
    assert blocked.dp_blocked.magnitude == pytest.approx(
        a.clean_drop(c.mdot_n, c.rho, c.mu, face, Cv, Ci, 0.5).magnitude)
    loaded = a.loaded_drop(c, water, screen)
    assert loaded.dp_loaded.magnitude == pytest.approx(
        a.cake_drop(c.mdot_n, c, Cv, Ci, 1e9*m/kg).magnitude)

    wall = a.boundary(c, water)
    stub = a.cylinder_vm(c.p_proof, c.stub_od, water.d_i)
    rim = a.cylinder_vm(c.p_burst, c.body_d, c.pocket_d)
    assert wall.sigma_stub_proof.to(MPa).magnitude == pytest.approx(stub.to(MPa).magnitude)
    assert wall.sigma_rim_burst.to(MPa).magnitude == pytest.approx(rim.to(MPa).magnitude)
    assert wall.MS_stub_proof.magnitude == pytest.approx((c.Sy/stub).to("").magnitude - 1)
    assert wall.MS_rim_burst.magnitude == pytest.approx((c.Su/rim).to("").magnitude - 1)

    weighed = a.assembly_mass(c)
    assert weighed.m_dry.magnitude == pytest.approx(a.mass(c).magnitude)
    assert weighed.MS_mass.magnitude == pytest.approx((c.mass_limit/(weighed.m_dry*c.growth_factor)).magnitude - 1)


def test_missing_calibration_sheet_preserves_reference_sweeps_and_csv(c, monkeypatch, tmp_path):
    import csv
    load = a.Sheet.load
    def missing_calibration(path, name):
        if name == "Calibration":
            raise KeyError("Worksheet Calibration does not exist")
        return load(path,name)
    monkeypatch.setattr(a.Sheet,"load",missing_calibration)
    monkeypatch.setattr(a,"ROOT",tmp_path)
    with pytest.raises(UnavailableInput,match="Calibration"):
        a.selected_table(c)
    assert len(a.flow_plot(c).series) == 3
    a.export_sweeps(c)
    rows = list(csv.DictReader((tmp_path/"output/sweeps.csv").open()))
    assert any(r["driver"] == "mass_flow" and float(r["y"]) > 0 for r in rows)
    assert any(r["driver"] == "rating" and r["y"] == "OPEN" for r in rows)
