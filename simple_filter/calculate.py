"""Only requested deterministic hand calculations; no old FEA or Monte Carlo."""
import json, math
from inputs import C,ROOT,LB_KG,PSI_PA

def calculate():
    cad=json.loads((ROOT/'output/cad/metadata.json').read_text())
    area=math.pi*(C['active_d']*.001)**2/4
    bore=math.pi*(C['stub_id']*.001)**2/4
    results={}
    for label,key in [('nominal','mdot_n'),('surge','mdot_s')]:
        mdot=C[key]*LB_KG; U=mdot/(C['rho_w']*area); V=mdot/(C['rho_w']*bore)
        screen=(C['Cv_f']+C['Cv_c'])*C['mu_w']*U+(C['Ci_f']+C['Ci_c'])*C['rho_w']*U**2
        body=C['K_body']*C['rho_w']*V**2/2
        cake=C['mu_w']*U*C['alpha_c']*(C['dirt_mass']*.001)/area
        results[label]=dict(flow_L_min=mdot/C['rho_w']*60000,U_m_s=U,bore_m_s=V,screen_psi=screen/PSI_PA,body_psi=body/PSI_PA,clean_psi=(screen+body)/PSI_PA,loaded_psi=(screen+body+cake)/PSI_PA)
    ri=C['pocket_d']/2;ro=C['body_d']/2;p=C['p_burst']*PSI_PA/1e6
    hoop=p*(ro**2+ri**2)/(ro**2-ri**2);axial=p*ri**2/(ro**2-ri**2);radial=-p
    vm=math.sqrt(((hoop-axial)**2+(axial-radial)**2+(radial-hoop)**2)/2)
    A_disc=math.pi*(C['frame_d']*.001)**2/4
    V_frame=math.pi*((C['frame_d']*.001)**2-(C['active_d']*.001)**2)/4*C['frame_raw_t']*.001
    housing=2*cad['housing_volume_mm3']*1e-9*C['rho_ti']
    frames=2*V_frame*C['rho_ss'];coarse=2*A_disc*C['coarse_areal_mass'];fine=A_disc*C['fine_areal_mass']
    dry=housing+frames+coarse+fine
    # Independent exact volume of a revolved polygon (boundary integral).
    from design import PROFILE
    v=abs(sum((z2-z1)*(r1*r1+r1*r2+r2*r2) for (r1,z1),(r2,z2) in zip(PROFILE,PROFILE[1:]+PROFILE[:1]))*math.pi/3)
    assert abs(v-cad['housing_volume_mm3'])<1e-5
    results.update(area_mm2=area*1e6,housing_volume_mm3=v,pressure_burst_MPa=dict(hoop=hoop,axial=axial,radial=radial,vm=vm),mass_kg=dict(housing_pair=housing,frame_pair=frames,coarse_pair=coarse,fine=fine,dry=dry,reserved=dry*C['growth_factor']),mass_lb=dry/LB_KG,reserved_mass_lb=dry*C['growth_factor']/LB_KG)
    (ROOT/'output/calculations.json').write_text(json.dumps(results,indent=2))
    return results
if __name__=='__main__':print(json.dumps(calculate(),indent=2))
