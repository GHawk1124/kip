"""Independent numerical consistency checks for the delivered engineering project."""
import json
import numpy as np
from design import *
from analysis import dp,LB,MU,RHO,AF,CV,CI
from fit_mesh import fit
from kip.doc import build

def main():
    c=json.loads((OUT/'analysis/cad.json').read_text())
    r=json.loads((OUT/'analysis/results.json').read_text())
    f=json.loads((OUT/'analysis/fem.json').read_text())
    p=np.array(PROFILE);q=np.roll(p,-1,axis=0)
    volume=abs(np.pi/3*np.sum((p[:,0]+q[:,0])*(p[:,0]*q[:,1]-q[:,0]*p[:,1])))
    assert abs(volume/c['housing_volume_mm3']-1)<1e-10
    assert c['solids']==7 and c['valid'] and not c['interference_mm3']
    assert c['dry_mass_kg']*1.2 < LB
    assert abs(dp(.47*LB)-r['clean_psi_70F'][1])<1e-10
    assert r['selective_meop_bounds_mm'][0]>.04
    assert r['selective_proof_bounds_mm'][0]>.04
    # Synthetic mathematical fixture ONLY: verifies recovery of known coefficients.
    dtype=[(s,float) for s in ['mdot_kg_s','dp_Pa','rho_kg_m3','mu_Pa_s','area_m2']]
    rows=np.zeros(9,dtype=dtype)
    rows['mdot_kg_s']=np.linspace(.02,.25,9)
    rows['rho_kg_m3']=RHO;rows['mu_Pa_s']=MU;rows['area_m2']=AF
    u=rows['mdot_kg_s']/RHO/AF
    rows['dp_Pa']=CV*MU*u+CI*RHO*u*u
    recovered=fit(rows)
    assert abs(recovered['Cv_per_m']/CV-1)<1e-10
    assert abs(recovered['Ci']/CI-1)<1e-10
    assert f['validation_Lame_relative_error']<.03
    for case in f['convergence']:
        assert abs(case['axial_force_N']+case['axial_reaction_N'])<1e-6
        assert case['relative_free_residual']<1e-7
    doc=build(path=ROOT/'doc.py')
    execution_errors=[(key,val.error) for key,val in doc.results.items() if not val.ok]
    assert not execution_errors,execution_errors
    calculated=doc.results['hyd_surge'].values['DP_s'].to('psi').magnitude
    assert abs(calculated-r['clean_psi_70F'][1])<1e-7
    mass=doc.results['mass_calc'].values['m_dry'].to('kg').magnitude
    assert abs(mass-c['dry_mass_kg'])<1e-9
    result={'numerical_checks':'PASS','checks':['Pappus/CAD volume','7 valid noninterfering solids',
        '20 percent mass reserve','hydraulic JSON vs unit-checked Kip result','selective stack at MEOP/proof',
        'NNLS mathematical recovery fixture','Lame benchmark','FEM force balance','all Kip blocks execute',
        'mass JSON vs Kip mass'],
        'qualification':'NOT ESTABLISHED; untested service requirements remain open'}
    (OUT/'analysis/verification.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
