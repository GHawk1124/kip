"""Shared design definition. Lengths mm, stresses MPa unless explicitly SI."""
from pathlib import Path
ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'output'
ASSETS = ROOT / 'assets'
for p in [OUT, ASSETS, OUT/'cad', OUT/'analysis', OUT/'qa']:
    p.mkdir(parents=True, exist_ok=True)

ACTIVE_D = 58.0
FRAME_D = 70.0
FRAME_T_RAW = .200
FINE_T = .180
COARSE_T = .480  # calender target; sourced raw construction is .508
LAND_H = .740
PROFILE = [  # positive half, (radius, axial z); mm. Revolve about Z.
    (41,0),(41,8),(40,10),(13.5,35),(9.525,38),(9.525,58),
    (7.875,58),(7.875,36),(11,33),(36,9),(35,7),(35,4.5),
    (29,4.5),(29,.820),(31.8,.820),(31.8,LAND_H),(32.2,LAND_H),
    (32.2,.820),(35.2,.820),(35.2,2),(37,2),(37,0),(38,0),
    (38,.150),(38.5,.150),(38.5,0),
]
# Surface segments wetted in equal-pressure LC-H. Includes groove/moat faces.
WET_SEGMENTS = [i for i in range(6,21) if i != 15] + [22,23,24]
COLORS = ['#879eaf','#e5b460','#6aa7b0','#285e79','#6aa7b0','#e5b460','#879eaf']
