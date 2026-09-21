"""Requirements and analysis for one object. Run: uv run doc.py"""
from kip import *

report = run_document(__file__)

reqs = Requirements.load()

# %% text "Scope"
"""Check the object's tensile capacity against @req:REQ-001."""

# %% table "Nomenclature"
nomenclature()

# %% controlled "Design requirements"
P = reqs.P_design
sigma_allow = reqs.sigma_allow

# %% inputs "Geometry"
A = 200 * mm**2  # Net area

# %% calc "Tensile stress"
sigma = P / A      # -> MPa

# %% calc margin "Margin of safety"
MS = sigma_allow / sigma - 1

# %% table "Verification matrix"
reqs.verify("REQ-001", MS, ">= 0", evidence="margin")
compliance_matrix(reqs, xlsx="verification.xlsx")
