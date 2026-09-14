"""Build123d manufacturing concept. Exactly seven solids; no discrete wire solids.
STEP screen discs are media envelopes, NOT impermeable plates or pore-resolved cloth.
Frame envelopes represent 0.030 mm coining per face at assembly.
"""
import json
import numpy as np
from kip.cad import load_build123d, cad_view, cad_section
from design import *
bd = load_build123d()

def make_models():
    profile = bd.Plane.XZ * bd.Polygon(*PROFILE, align=None)
    upper = bd.revolve(profile, axis=bd.Axis.Z)
    upper.label = 'F100-01 housing A; identical to B'
    lower = bd.Rot(X=180) * upper
    lower.label = 'F100-01 housing B'
    fine = bd.Cylinder(FRAME_D/2,FINE_T)
    fine.label = 'F100-04 RPD HIFLO 5-S media envelope'
    coarse_a = bd.Pos(Z=.09+.24)*bd.Cylinder(FRAME_D/2, COARSE_T)
    coarse_b = bd.Pos(Z=-.09-.24)*bd.Cylinder(FRAME_D/2, COARSE_T)
    coarse_a.label='F100-03 coarse A; calendered envelope'
    coarse_b.label='F100-03 coarse B; calendered envelope'
    frame = bd.extrude(bd.Circle(FRAME_D/2)-bd.Circle(ACTIVE_D/2), amount=.17)
    frame_a = bd.Pos(Z=.57)*frame
    frame_b = bd.Rot(X=180)*frame_a
    frame_a.label='F100-02 frame A; coined envelope'
    frame_b.label='F100-02 frame B; coined envelope'
    parts = [upper,frame_a,coarse_a,fine,coarse_b,frame_b,lower]
    assembly = bd.Compound(children=parts)
    assembly.label='F100 seven-component water filter Rev A0'
    dz=[36,23,12,0,-12,-23,-36]
    exploded=bd.Compound(children=[bd.Pos(Z=z)*s for z,s in zip(dz,parts)])
    return parts,assembly,exploded

def mesh_poly(shape):
    import pyvista as pv
    vertices,triangles=shape.tessellate(.12,.18)
    pts=np.array([[v.X,v.Y,v.Z] for v in vertices])
    faces=np.column_stack([np.full(len(triangles),3),np.array(triangles)]).ravel()
    return pv.PolyData(pts,faces).clean(tolerance=1e-8).compute_normals(
        split_vertices=True,feature_angle=25,consistent_normals=True,auto_orient_normals=True)

def render(parts, name, exploded=False, cut=False):
    import pyvista as pv
    p=pv.Plotter(off_screen=True,window_size=(1800,1350))
    for i, s in enumerate(parts):
        if cut:
            sectioned=s.intersect(bd.Pos(0,50,0)*bd.Box(200,100,220))
            if isinstance(sectioned,list): sectioned=bd.Compound(children=sectioned)
            m=mesh_poly(sectioned)
        else:
            m=mesh_poly(s)
        if exploded: m.translate([0,0,[36,23,12,0,-12,-23,-36][i]],inplace=True)
        p.add_mesh(m,color=COLORS[i],smooth_shading=True, specular=.4, specular_power=30)
    p.camera_position=[(150,-215,140),(0,0,0),(0,0,1)]
    p.enable_parallel_projection()
    p.camera.zoom(1.15)
    p.screenshot(str(ASSETS/f'{name}.png'),transparent_background=True)
    p.close()

def main():
    parts,a,e=make_models()
    for s in parts: assert s.is_valid and len(s.solids())==1
    assert len(a.solids())==7
    # Check all solid pair intersections; coined sheet envelopes just touch lands.
    overlaps=[]
    for i in range(7):
        for j in range(i+1,7):
            intersection=parts[i].intersect(parts[j])
            vol=intersection.volume if intersection else 0
            if vol>1e-5: overlaps.append([i,j,vol])
    assert not overlaps, overlaps
    bd.export_step(a,OUT/'cad/filter_assembly.step')
    bd.export_step(e,OUT/'cad/filter_exploded.step')
    bd.export_step(bd.Part(parts[0].wrapped),OUT/'cad/housing_half.step')
    bd.export_step(bd.extrude(bd.Circle(FRAME_D/2)-bd.Circle(ACTIVE_D/2),amount=.2),OUT/'cad/frame_blank.step')
    for name,shape,view in [('assembly_iso',a,'iso'),('exploded_iso',e,'iso'),
                            ('housing_iso',parts[0],'iso'),('front',a,'front'),('end',a,'top')]:
        d=cad_view(shape,view,width=155)
        (ASSETS/f'{name}.svg').write_bytes(d.svg)
    d=cad_section(a,bd.Plane.XZ,dxf='filter_section_AA.dxf',width=150)
    (ASSETS/'section_cad.svg').write_bytes(d.svg)
    for name,data in d.attachments.items(): (OUT/'cad'/name).write_bytes(data)
    render(parts,'hero')
    render(parts,'exploded_render',True)
    render(parts,'cutaway',cut=True)
    mass_h=parts[0].volume*4.51e-6
    area=np.pi*(FRAME_D/1000)**2/4
    frames=2*np.pi*((FRAME_D/2)**2-(ACTIVE_D/2)**2)*.2*8e-6
    coarse=2*area*(.280*.45359237/.09290304)
    fine=area*.95
    info=dict(solids=7,valid=True,interference_mm3=overlaps,
              housing_volume_mm3=parts[0].volume,housing_mass_kg=mass_h,
              frame_pair_kg=frames,coarse_pair_kg=coarse,fine_kg=fine,
              dry_mass_kg=2*mass_h+frames+coarse+fine,
              envelope_mm=[82,82,116])
    (OUT/'analysis/cad.json').write_text(json.dumps(info,indent=2))
    print(json.dumps(info,indent=2))

if __name__=='__main__': main()
