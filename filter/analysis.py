"""Reproducible screening calculations, not test data or qualification probability."""
import json
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy.optimize import brentq
from design import *
PSI=6894.757293
LB=.45359237
AF=np.pi*(ACTIVE_D/1000)**2/4
RHO=997.99
MU=.000979 # water at 70 F (21.11 C), engineering interpolation
CV=6e7   # hypothesis, NOT supplier fit
CI=3000  # hypothesis, NOT supplier fit
K=3.0    # total stub/transition loss coefficient on bore velocity
BORE=.01575
AB=np.pi*BORE**2/4
MD=.000318

def dp(mdot,mu=MU,rho=RHO,cv=CV,ci=CI,alpha=0,area=AF,k=K):
    u=mdot/rho/area
    v=mdot/rho/AB
    # two coarse supports given an explicitly assumed series allowance
    screen=(cv+2e5)*mu*u+(ci+40)*rho*u*u
    body=k*rho*v*v/2
    cake=mu*u*alpha*MD/area
    return (screen+body+cake)/PSI

def savefig(fig,name):
    fig.savefig(ASSETS/f'{name}.svg',bbox_inches='tight',transparent=True)
    fig.savefig(ASSETS/f'{name}.png',dpi=200,bbox_inches='tight',transparent=True)
    plt.close(fig)

def main():
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False,
                          'axes.labelcolor':'#243b50','text.color':'#243b50',
                          'svg.fonttype':'none'})
    rng=np.random.default_rng(6501300)
    n=100000
    # Epistemic exploration: priors are analyst assumptions, not manufacturing data.
    cv=np.exp(rng.uniform(np.log(2e7),np.log(2e8),n))
    ci=np.exp(rng.uniform(np.log(300),np.log(10000),n))
    temp=np.full(n,21.111111)
    mu=MU
    alpha=np.exp(rng.uniform(np.log(1e8),np.log(1e11),n))
    k=rng.uniform(1.5,6,n)
    area=np.pi*(rng.uniform(ACTIVE_D-.1,ACTIVE_D+.1,n)*.001)**2/4
    cn=dp(.14*LB,mu,cv=cv,ci=ci,area=area,k=k)
    cs=dp(.47*LB,mu,cv=cv,ci=ci,area=area,k=k)
    ld=dp(.14*LB,mu,cv=cv,ci=ci,alpha=alpha,area=area,k=k)
    # Dimensional tolerance sensitivity: independent bounded uniform variables.
    t=rng.uniform(1.534,1.546,n)
    ha=rng.uniform(.737,.743,n); hb=rng.uniform(.737,.743,n)
    form=rng.uniform(-.004,.004,n)
    shrink=rng.uniform(0,.012,n)
    recovery=rng.uniform(0,.008,n)
    fem_path=OUT/'analysis/fem.json'
    opening=json.loads(fem_path.read_text())['convergence'][-1]['land_opening_mm'] if fem_path.exists() else .003403
    crush=t-ha-hb+form+shrink-recovery-opening
    matched=(t-ha-hb>=.060)&(t-ha-hb<=.065)
    u=.14*LB/RHO/AF; us=.47*LB/RHO/AF
    alimit=(18-dp(.14*LB))*PSI*AF/(MU*u*MD)
    alimitcold=(18-dp(.14*LB,.001519))*PSI*AF/(.001519*u*MD)
    cvlim=(5*PSI-K*RHO*(.47*LB/RHO/AB)**2/2-(CI+40)*RHO*us**2)/(.001519*us)-2e5
    free=brentq(lambda f: ((CV+2e5)*MU*u/f+(CI+40)*RHO*u*u/f**2)/PSI+K*RHO*(.14*LB/RHO/AB)**2/2/PSI-18,.001,1)
    # Optimistic upper capacity of one coarse cloth: full yield line tension,
    # sin(theta)=1; disc strain and pore retention omitted. Failure is decisive.
    aw=np.pi*.254**2/4
    line_y=2*aw/.635*170  # N/mm
    line_u=2*aw/.635*485
    cap_y=2*np.pi*(ACTIVE_D/2)*line_y
    cap_u=2*np.pi*(ACTIVE_D/2)*line_u
    loads={str(p):p*PSI*AF for p in [18,650,1300,2600]}
    seat_area=np.pi*64*.4 # mm2
    coining_force=seat_area*np.array([250,450])
    # Ideal fully open uniform annular slit at 650 psid; leakage sensitivity only.
    qtot=.14*LB/RHO
    hlim=(.001*qtot*6*MU*np.log(32.2/31.8)/(np.pi*18*PSI))**(1/3)
    report={
        'area_m2':AF,'flow_Lmin_nominal':.14*LB/RHO*60000,
        'flow_Lmin_surge':.47*LB/RHO*60000,'face_velocity_m_s':[u,us],
        'bore_velocity_m_s':[.14*LB/RHO/AB,.47*LB/RHO/AB],
        'nominal_cv_hypothesis':CV,'nominal_ci_hypothesis':CI,
        'clean_psi_70F':[dp(.14*LB),dp(.47*LB)],
        'clean_psi_5C':[dp(.14*LB,.001519),dp(.47*LB,.001519)],
        'loaded_psi_alpha_1e9':[dp(.14*LB,alpha=1e9),dp(.47*LB,alpha=1e9)],
        'alpha_limit_70F_m_kg':alimit,'alpha_limit_5C_m_kg':alimitcold,
        'cv_limit_cold_surge_per_m':cvlim,'blocked_fraction_at_18psi':1-free,
        'mc_n':n,'mc_seed':6501300,'mc_screening_only':True,
        'mc_clean_nominal_fraction':float(np.mean(cn<=5)),
        'mc_clean_surge_fraction':float(np.mean(cs<=5)),
        'mc_loaded_nominal_fraction':float(np.mean(ld<=18)),
        'mc_joint_fraction':float(np.mean((cs<=5)&(ld<=18))),
        'mc_crush_fraction':float(np.mean((crush>=.04)&(crush<=.09))),
        'selective_pairing_fraction':float(np.mean(matched)),
        'selective_geometric_fraction':float(np.mean((crush[matched]>=.04)&(crush[matched]<=.09))),
        'selective_meop_bounds_mm':[.060-.004-.008-opening,.065+.004+.012-opening],
        'selective_proof_bounds_mm':[.060-.004-.008-2*opening,.065+.004+.012-2*opening],
        'mc_crush_quantiles_um':(1000*np.quantile(crush,[.001,.5,.999])).tolist(),
        'mc_crush_worst_mm':[.036-opening,.088-opening],
        'fem_opening_mm_applied_to_crush':opening,
        'pressure_forces_N':loads,'coarse_optimistic_yield_N':cap_y,
        'coarse_optimistic_ultimate_N':cap_u,
        'coining_force_N':coining_force.tolist(),
        'full_annular_slit_0_1pct_limit_um':hlim*1e6,
        'thermal_diffusion_length_mm_10s':np.sqrt(21.79/(4510*520)*10)*1000,
    }
    (OUT/'analysis/results.json').write_text(json.dumps(report,indent=2))
    np.savez_compressed(OUT/'analysis/monte_carlo.npz',cv=cv,ci=ci,temp_C=temp,
                        alpha=alpha,clean_nominal_psi=cn,clean_surge_psi=cs,
                        loaded_nominal_psi=ld,crush_mm=crush)
    flow=np.linspace(.02,.55,160)
    fig,ax=plt.subplots(figsize=(8,3.6))
    for cvv,lbl in [(2e7,'Low resistance hypothesis'),(6e7,'Baseline hypothesis'),(2e8,'High resistance hypothesis')]:
        ax.plot(flow,dp(flow*LB,cv=cvv),label=lbl)
    ax.axhline(5,color='#bb673e',ls='--',label='Clean limit')
    ax.axvline(.14,color='#aaa',ls=':');ax.axvline(.47,color='#aaa',ls=':')
    ax.set(xlabel='Water mass flow (lbm/s)',ylabel='Assembly pressure drop (psi)',title='Water at 70 °F / 58 mm active face')
    ax.legend(fontsize=8);savefig(fig,'hydraulics')
    fig,ax=plt.subplots(figsize=(8,3.6))
    al=np.logspace(8,11,150)
    ax.semilogx(al,dp(.14*LB,alpha=al),label='Nominal / 70 °F')
    ax.semilogx(al,dp(.47*LB,alpha=al),label='Surge / 70 °F')
    ax.axhline(18,color='#bb673e',ls='--',label='Loaded limit')
    ax.set(xlabel='Specific cake resistance (m/kg)',ylabel='Assembly pressure drop (psi)',ylim=(0,60),title='0.318 g retained dry dirt / cake model only')
    ax.legend(fontsize=8);savefig(fig,'dirt')
    fig,(ax,bx)=plt.subplots(1,2,figsize=(8,3.5))
    ax.hist(cs,bins=70,color='#39788b');ax.axvline(5,color='#bb673e',ls='--')
    ax.set(xlabel='Clean surge pressure drop (psi)',ylabel='Assumed samples')
    bx.hist(crush*1000,bins=70,color='#c8954c')
    bx.axvline(40,color='#bb673e',ls='--');bx.axvline(90,color='#bb673e',ls='--')
    bx.set(xlabel='Residual geometric crush (µm)',ylabel='Assumed samples')
    fig.suptitle('100,000 assumed draws / sensitivity, not reliability')
    fig.tight_layout();savefig(fig,'monte_carlo')
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
