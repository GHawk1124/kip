"""Requirements and analysis for one object. Run: uv run kip build"""
from kip import *

reqs = Requirements.load("requirements.toml")

# %% text scope "Scope" wrap_title=true
"""Check the object's tensile capacity against @req:REQ-001."""

# %% table symbols "Nomenclature"
symbols = nomenclature({
    "P": ("Required load", "kN"),
    "A": ("Net area", "mm²"),
    "sigma": ("Tensile stress", "MPa"),
    "sigma_allow": ("Allowable stress", "MPa"),
    "MS": "Margin of safety",
})

# %% controlled loads "Design requirements"
P = reqs.P_design
sigma_allow = reqs.sigma_allow

# %% inputs geometry "Geometry"
A = 200 * mm**2

# %% calc stress "Tensile stress" unit=MPa
sigma = P / A

# %% calc margin "Margin of safety"
MS = sigma_allow / sigma - 1

# %% table compliance "Verification matrix"
reqs.verify("REQ-001", MS, ">= 0", evidence="margin")
compliance = compliance_matrix(reqs, xlsx="verification.xlsx")
