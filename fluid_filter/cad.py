"""Seven-piece filter: one revolved cup profile and a mirrored media stack."""
import json

from kip import Constants, mm
from kip.cad import load_build123d, cad_view, cad_section
import analysis as a


def build(c):
    bd = load_build123d()
    d = {key:c.value(key,mm) for key in ("frame_d","active_d","fine_t","coarse_t","frame_assembled_t")}
    upper = bd.revolve(bd.Plane.XZ * bd.Polygon(*a.profile(c),align=None),axis=bd.Axis.Z)
    lower = bd.Rot(X=180) * upper
    fine = bd.Cylinder(d["frame_d"]/2,d["fine_t"])
    coarse_z = (d["fine_t"]+d["coarse_t"])/2
    coarse = bd.Pos(Z=coarse_z) * bd.Cylinder(d["frame_d"]/2,d["coarse_t"])
    annulus = bd.Circle(d["frame_d"]/2) - bd.Circle(d["active_d"]/2)
    frame = bd.Pos(Z=d["fine_t"]/2+d["coarse_t"]) * bd.extrude(annulus,amount=d["frame_assembled_t"])
    parts = [upper,frame,coarse,fine,bd.Rot(X=180)*coarse,bd.Rot(X=180)*frame,lower]
    labels = ["Ti Grade 2 cup A","316L frame A","316 support A","316 Dutch-twill cloth envelope",
              "316 support B","316L frame B","Ti Grade 2 cup B"]
    for part,label in zip(parts,labels):
        part.label = label
        if not part.is_valid or len(part.solids()) != 1:
            raise ValueError(f"Invalid CAD solid: {label}")
    expected = a.housing_volume(c).to(mm**3).magnitude
    if abs(upper.volume-expected) > 1e-6*expected:
        raise ValueError("Revolved CAD volume does not match independent section integration")
    for i,p in enumerate(parts):
        for q in parts[i+1:]:
            common = p.intersect(q)
            if common and common.volume > 1e-5:
                raise ValueError(f"Interference: {p.label} / {q.label}")
    return parts, bd.Compound(children=parts)


def generate():
    bd = load_build123d()
    c = Constants.load(a.BOOK)
    parts,assembly = build(c)
    assets,out = a.ROOT/"assets", a.ROOT/"output"
    assets.mkdir(exist_ok=True)
    (out/"cad").mkdir(parents=True,exist_ok=True)
    bd.export_step(assembly,out/"cad/fluid_filter.step")
    bd.export_step(bd.Part(parts[0].wrapped),out/"cad/housing_half.step")
    section = cad_section(assembly,bd.Plane.XZ,dxf="axial_section.dxf")
    views = {"assembly":cad_view(assembly),"section":section}
    for name,drawing in views.items():
        (assets/f"{name}.svg").write_bytes(drawing.svg)
        for filename,data in drawing.attachments.items():
            (out/"cad"/filename).write_bytes(data)
    (out/"cad/checks.json").write_text(json.dumps({
        "components":len(parts),"interferences":0,"valid_solids":True,
        "housing_volume_mm3":parts[0].volume,
        "independent_volume_mm3":a.housing_volume(c).to(mm**3).magnitude,
        "stub_od_in":c.value("stub_od","inch"),"stub_wall_in":c.value("stub_wall","inch"),
        "stub_id_in":a.bore(c.stub_od,c.stub_wall).to("inch").magnitude},indent=2))
    a.export_sweeps(c)
    print("CAD checked: seven valid solids, no interference, housing volume independently matched.")


def component_count():
    return json.loads((a.ROOT/"output/cad/checks.json").read_text())["components"]


if __name__ == "__main__":
    generate()
