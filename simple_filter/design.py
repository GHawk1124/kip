"""Simple, axisymmetric cup with one flat seat and one combined closure/weld rim."""
from inputs import ROOT,C
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
