"""Axisymmetric small-strain elastic housing screening, CST triangles.
Units: mm, N, MPa. Three integration points; full hoop strain N/r.
Equal internal pressure both sides, ideal continuous welded rim, no seal preload.
Sharp-corner peaks are mesh dependent. Not nonlinear burst/contact analysis.
"""
import json
import numpy as np
import gmsh
from scipy.sparse import coo_matrix
from scipy.sparse.linalg import spsolve
import meshio
from design import *
E=105000.0; NU=.34 # CP titanium Grade 2 housing assumptions
P=650*6894.757293/1e6

def mesh_polygon(profile,size):
    gmsh.initialize()
    gmsh.option.setNumber('General.Terminal',0)
    gmsh.model.add('axisymmetric_housing')
    pts=[gmsh.model.geo.addPoint(r,z,0,size) for r,z in profile]
    lines=[gmsh.model.geo.addLine(pts[i],pts[(i+1)%len(pts)]) for i in range(len(pts))]
    loop=gmsh.model.geo.addCurveLoop(lines)
    gmsh.model.geo.addPlaneSurface([loop]);gmsh.model.geo.synchronize()
    gmsh.model.mesh.generate(2)
    tags,coords,_=gmsh.model.mesh.getNodes()
    coords=np.array(coords).reshape(-1,3)[:,:2]
    index={int(tag):i for i,tag in enumerate(tags)}
    _,ets,nds=gmsh.model.mesh.getElements(2)
    tris=np.array([[index[int(n)] for n in tri] for tri in np.array(nds[0]).reshape(-1,3)])
    boundaries=[]
    for line in lines:
        _,_,nodes=gmsh.model.mesh.getElements(1,line)
        boundaries.append(np.array([[index[int(n)] for n in edge] for edge in np.array(nodes[0]).reshape(-1,2)]))
    gmsh.finalize()
    return coords,tris,boundaries

def solve(coords,tris,boundaries,profile,wet,pressure,fixed_segments,end_segment):
    lam=E*NU/((1+NU)*(1-2*NU));mu=E/(2*(1+NU))
    D=np.zeros((4,4));D[:3,:3]=lam
    D[0,0]+=2*mu;D[1,1]+=2*mu;D[2,2]+=2*mu;D[3,3]=mu
    rows=[];cols=[];vals=[];Bs=[];weights=[]
    for tr in tris:
        xy=coords[tr];C=np.column_stack([np.ones(3),xy])
        det=np.linalg.det(C);area=abs(det)/2
        deriv=np.linalg.inv(C)[1:,:]
        ke=np.zeros((6,6));rbar=xy[:,0].mean()
        for N in [np.array([2/3,1/6,1/6]),np.array([1/6,2/3,1/6]),np.array([1/6,1/6,2/3])]:
            r=N@xy[:,0]; B=np.zeros((4,6))
            B[0,0::2]=deriv[0];B[1,1::2]=deriv[1];B[2,0::2]=N/r
            B[3,0::2]=deriv[1];B[3,1::2]=deriv[0]
            ke+=B.T@D@B*2*np.pi*r*area/3
        N=np.ones(3)/3;B[2,0::2]=N/rbar
        Bs.append(B.copy());weights.append(2*np.pi*rbar*area)
        ids=np.array([[2*i,2*i+1] for i in tr]).ravel()
        rows.extend(np.repeat(ids,6));cols.extend(np.tile(ids,6));vals.extend(ke.ravel())
    ndof=2*len(coords);K=coo_matrix((vals,(rows,cols)),shape=(ndof,ndof)).tocsr()
    f=np.zeros(ndof)
    # Consistent pressure loads with radial weighting, 2-point line integration.
    for seg in wet:
        p0=np.array(profile[seg]);p1=np.array(profile[(seg+1)%len(profile)])
        vec=p1-p0;norm=np.array([-vec[1],vec[0]])/np.linalg.norm(vec)
        for edge in boundaries[seg]:
            xy=coords[edge];length=np.linalg.norm(xy[1]-xy[0])
            for xi in [-1/np.sqrt(3),1/np.sqrt(3)]:
                N=np.array([(1-xi)/2,(1+xi)/2]);r=N@xy[:,0]
                for a,node in enumerate(edge):f[2*node:2*node+2]+=N[a]*pressure*norm*2*np.pi*r*length/2
    # Closed-end bore pressure transferred by attached line, uniformly over tube wall.
    a,b=np.array(profile[end_segment]),np.array(profile[(end_segment+1)%len(profile)])
    ro=max(a[0],b[0]);ri=min(a[0],b[0]);traction=pressure*ri**2/(ro**2-ri**2)
    for edge in boundaries[end_segment]:
        xy=coords[edge];length=np.linalg.norm(xy[1]-xy[0])
        for xi in [-1/np.sqrt(3),1/np.sqrt(3)]:
            N=np.array([(1-xi)/2,(1+xi)/2]);r=N@xy[:,0]
            for a,node in enumerate(edge):f[2*node+1]+=N[a]*traction*2*np.pi*r*length/2
    fixed=np.unique(np.concatenate([boundaries[i].ravel()*2+1 for i in fixed_segments]))
    free=np.setdiff1d(np.arange(ndof),fixed)
    u=np.zeros(ndof);u[free]=spsolve(K[free][:,free],f[free])
    residual=K@u-f
    stress=[]
    for tr,B in zip(tris,Bs):
        ids=np.array([[2*i,2*i+1] for i in tr]).ravel()
        stress.append(D@B@u[ids])
    stress=np.array(stress)
    vm=np.sqrt(.5*((stress[:,0]-stress[:,1])**2+(stress[:,1]-stress[:,2])**2+(stress[:,2]-stress[:,0])**2)+3*stress[:,3]**2)
    return u.reshape(-1,2),stress,vm,dict(relative_free_residual=float(np.linalg.norm(residual[free])/np.linalg.norm(f[free])),
          axial_force_N=float(f[1::2].sum()),axial_reaction_N=float(residual[1::2].sum()),strain_energy_Nmm=float(.5*u@K@u))

def main():
    results=[]
    for size in [1.2,.7,.4]:
        xy,tr,edges=mesh_polygon(PROFILE,size)
        u,stress,vm,diag=solve(xy,tr,edges,PROFILE,WET_SEGMENTS,P,[21,25],5)
        cent=xy[tr].mean(axis=1)
        # Smooth tube region for convergence; geometric corner peaks kept separate.
        tube=(cent[:,1]>45)&(cent[:,1]<53)
        cone=(cent[:,1]>17)&(cent[:,1]<26)
        land=np.unique(edges[15]);opening=2*float(np.mean(u[land,1]))
        results.append(dict(size_mm=size,nodes=len(xy),elements=len(tr),
                peak_vm_MPa=float(vm.max()),tube_vm_mean_MPa=float(vm[tube].mean()),
                cone_vm_mean_MPa=float(vm[cone].mean()),land_opening_mm=opening,**diag))
    # Validation: thick cylinder with closed end; compare Lame at centroids.
    rectangle=[(6.35,0),(6.35,20),(4.7,20),(4.7,0)]
    xyv,trv,edv=mesh_polygon(rectangle,.35)
    uv,sv,vmv,dv=solve(xyv,trv,edv,rectangle,[2],P,[3],1)
    cv=xyv[trv].mean(axis=1);rr=cv[:,0]
    A=P*4.7**2/(6.35**2-4.7**2);B=P*4.7**2*6.35**2/(6.35**2-4.7**2)
    exact=np.column_stack([A-B/rr**2,np.full(len(rr),A),A+B/rr**2,np.zeros(len(rr))])
    valid=(cv[:,1]>4)&(cv[:,1]<16)
    error=float(np.linalg.norm((sv-exact)[valid])/np.linalg.norm(exact[valid]))
    assert error<.03,error
    assert results[-1]['relative_free_residual']<1e-7
    # Axisymmetric 2D result file; ParaView can inspect or use swept 3D companion.
    meshio.write(OUT/'analysis/housing_axisymmetric.vtu',meshio.Mesh(np.column_stack([xy,np.zeros(len(xy))]),
        [('triangle',tr)],point_data={'u_rz_mm':np.column_stack([u,np.zeros(len(u))])},
        cell_data={'von_Mises_MPa':[vm],'sigma_rr_MPa':[stress[:,0]],'sigma_zz_MPa':[stress[:,1]],'sigma_tt_MPa':[stress[:,2]]}))
    # Sweep each triangle into wedge cells over 270 degrees, leaving cut faces visible.
    angles=np.linspace(0,1.5*np.pi,61);nn=len(xy)
    points=np.concatenate([np.column_stack([xy[:,0]*np.cos(t),xy[:,0]*np.sin(t),xy[:,1]]) for t in angles])
    displacement=np.concatenate([np.column_stack([u[:,0]*np.cos(t),u[:,0]*np.sin(t),u[:,1]]) for t in angles])
    wedges=np.concatenate([np.column_stack([tr+j*nn,tr+(j+1)*nn]) for j in range(len(angles)-1)])
    meshio.write(OUT/'analysis/housing_pressure_650psi.vtu',meshio.Mesh(points,[('wedge',wedges)],
        point_data={'displacement_mm':displacement},cell_data={'von_Mises_MPa':[np.tile(vm,len(angles)-1)]}))
    import pyvista as pv
    model=pv.read(OUT/'analysis/housing_pressure_650psi.vtu')
    p=pv.Plotter(off_screen=True,window_size=(1700,1400))
    p.add_mesh(model,scalars='von_Mises_MPa',cmap='viridis',clim=[0,110],show_scalar_bar=True,
        scalar_bar_args={'title':'von Mises / MPa at 650 psi','color':'#243b50','vertical':False,'width':.65,'position_x':.17})
    p.camera_position=[(100,-135,100),(0,0,24),(0,0,1)];p.enable_parallel_projection()
    p.screenshot(str(ASSETS/'pressure_render.png'),transparent_background=True);p.close()
    result={'load_psi':650,'model':'linear elastic, axisymmetric, ideal welded symmetry',
            'validation_Lame_relative_error':error,'convergence':results}
    (OUT/'analysis/fem.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
