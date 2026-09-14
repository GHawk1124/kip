"""Build123d housing, seven-part assembly, exports and transparent views."""
import json
import numpy as np
from kip.cad import load_build123d, cad_view, cad_section
"""Simple, axisymmetric cup with one flat seat and one combined closure/weld rim."""
from analysis import ROOT,C
OUT=ROOT/'output'; ASSETS=ROOT/'assets'
for p in [OUT,ASSETS,OUT/'cad',OUT/'qa']:p.mkdir(parents=True,exist_ok=True)
ACTIVE_D=C['active_d']; FRAME_D=C['frame_d']; FRAME_T_RAW=C['frame_raw_t']
FINE_T=C['fine_t']; COARSE_T=C['coarse_t']; FRAME_T=C['frame_assembled_t']
LAND_H=FINE_T/2+COARSE_T+FRAME_T
PROFILE=[(C['body_d']/2,0),(C['body_d']/2,C['outer_shoulder_z']),
(C['stub_od']/2,C['stub_start_z']),(C['stub_od']/2,C['half_length']),
(C['stub_id']/2,C['half_length']),(C['stub_id']/2,C['stub_start_z']),
(ACTIVE_D/2,C['inner_shoulder_z']),(ACTIVE_D/2,LAND_H),
(C['pocket_d']/2,LAND_H),(C['pocket_d']/2,0)]
assert C['body_d']>C['pocket_d']>FRAME_D>ACTIVE_D>C['stub_id']
assert C['stub_od']>C['stub_id'] and C['half_length']>C['stub_start_z']>C['inner_shoulder_z']>LAND_H
COLORS=['#879eaf','#e5b460','#6aa7b0','#285e79','#6aa7b0','#e5b460','#879eaf']

bd = load_build123d()

def make_models():
    profile = bd.Plane.XZ * bd.Polygon(*PROFILE, align=None)
    upper = bd.revolve(profile, axis=bd.Axis.Z)
    upper.label = 'F100-01 housing A; identical to B'
    lower = bd.Rot(X=180) * upper
    lower.label = 'F100-01 housing B'
    fine = bd.Cylinder(FRAME_D/2,FINE_T)
    fine.label = 'F100-04 Dutch twill candidate media envelope'
    coarse_a = bd.Pos(Z=FINE_T/2+COARSE_T/2)*bd.Cylinder(FRAME_D/2, COARSE_T)
    coarse_b = bd.Pos(Z=-FINE_T/2-COARSE_T/2)*bd.Cylinder(FRAME_D/2, COARSE_T)
    coarse_a.label='F100-03 coarse A; calendered envelope'
    coarse_b.label='F100-03 coarse B; calendered envelope'
    frame = bd.extrude(bd.Circle(FRAME_D/2)-bd.Circle(ACTIVE_D/2), amount=FRAME_T)
    frame_a = bd.Pos(Z=FINE_T/2+COARSE_T)*frame
    frame_b = bd.Rot(X=180)*frame_a
    frame_a.label='F100-02 frame A; coined envelope'
    frame_b.label='F100-02 frame B; coined envelope'
    parts = [upper,frame_a,coarse_a,fine,coarse_b,frame_b,lower]
    assembly = bd.Compound(children=parts)
    assembly.label='F100 simple seven-component water filter Rev S0'
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
    from PIL import Image
    path=ASSETS/f'{name}.png'
    with Image.open(path) as im:
        im.crop(im.getbbox()).save(path)

def circular_detail(parts, center, radius, name):
    """True CAD faces clipped to a circular detail boundary, no redrawn geometry."""
    svg = bd.ExportSVG(margin=radius*.04)
    disk = bd.Circle(radius)
    for i, part in enumerate(parts):
        section = bd.Plane.XZ.to_local_coords(bd.section(part, section_by=bd.Plane.XZ))
        section = bd.Pos(-center, 0) * section
        clipped = section.intersect(disk)
        if isinstance(clipped, list): clipped = bd.Compound(children=clipped)
        if clipped is None or not clipped.edges(): continue
        color = (222, 229, 233) if i in (0, 6) else ((229, 180, 96) if i in (1, 5) else (106, 167, 176))
        svg.add_layer(f'part_{i}', fill_color=color, line_weight=radius*.004)
        svg.add_shape(clipped, layer=f'part_{i}')
    svg.add_layer('boundary', line_weight=radius*.008)
    svg.add_shape(disk.face().outer_wire(), layer='boundary')
    svg.write(ASSETS/f'{name}.svg')


def generate():
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
    bd.export_step(bd.extrude(bd.Circle(FRAME_D/2)-bd.Circle(ACTIVE_D/2),amount=FRAME_T_RAW),OUT/'cad/frame_blank.step')
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
    detail = a.intersect(bd.Pos((ACTIVE_D/2+C['body_d']/2)/2,0,0)*bd.Box(C['body_d']/2-ACTIVE_D/2+2,2,5))
    if isinstance(detail,list): detail=bd.Compound(children=detail)
    cut=bd.Plane.XZ.to_local_coords(bd.section(detail,section_by=bd.Plane.XZ))
    svg=bd.ExportSVG(margin=0.5)
    svg.add_layer('section',line_weight=0.025)
    svg.add_shape(cut,layer='section')
    svg.write(ASSETS/'detail_b.svg')
    dxf=bd.ExportDXF()
    dxf.add_shape(cut)
    dxf.write(OUT/'cad/detail_B.dxf')
    circular_detail(parts, (ACTIVE_D/2+C['body_d']/2)/2, 5.2, 'detail_circle')
    pack=bd.Compound(children=[bd.Pos(Z=z)*s for z,s in zip([8,4,0,-4,-8],parts[1:6])])
    (ASSETS/'element.svg').write_bytes(cad_view(pack,'iso',width=160).svg)
    volume=abs(sum((z2-z1)*(r1*r1+r1*r2+r2*r2) for (r1,z1),(r2,z2) in zip(PROFILE,PROFILE[1:]+PROFILE[:1]))*np.pi/3)
    assert abs(volume-parts[0].volume)<1e-5
    info=dict(solids=7,valid=True,interference_mm3=overlaps,
              housing_volume_mm3=parts[0].volume,
              envelope_mm=[C['body_d'],C['body_d'],2*C['half_length']])
    (OUT/'cad/metadata.json').write_text(json.dumps(info,indent=2))
    print(json.dumps(info,indent=2))

def metadata():
    return json.loads((OUT/'cad/metadata.json').read_text())

if __name__=='__main__': generate()
