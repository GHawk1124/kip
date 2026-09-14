"""Fit an actual measured/supplier CSV, when obtained. No invented test dataset.
CSV columns: mdot_kg_s,dp_Pa,rho_kg_m3,mu_Pa_s,area_m2.
Pressure drop must be mesh-only, with empty-holder loss subtracted.
"""
import sys,json
import numpy as np
from scipy.optimize import nnls

def fit(rows):
    u=rows['mdot_kg_s']/rows['rho_kg_m3']/rows['area_m2']
    basis=np.column_stack([rows['mu_Pa_s']*u,rows['rho_kg_m3']*u*u])
    # Scale each column so coefficient units do not spoil conditioning.
    scale=np.linalg.norm(basis,axis=0)
    coefficients,residual=nnls(basis/scale,rows['dp_Pa'])
    cv,ci=coefficients/scale
    pred=basis@np.array([cv,ci])
    return dict(Cv_per_m=float(cv),Ci=float(ci),residual_L2_Pa=float(residual),
        max_abs_residual_Pa=float(np.max(abs(pred-rows['dp_Pa']))),
        normalized_condition_number=float(np.linalg.cond(basis/scale)),
        note='Inspect residuals, uncertainty and independent validation before use.')

if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit('Usage: uv run python fit_mesh.py measured_mesh.csv')
    rows=np.genfromtxt(sys.argv[1],delimiter=',',names=True)
    if len(rows)<5:raise ValueError('Need at least five independent flow points.')
    print(json.dumps(fit(rows),indent=2))
