"""Edit this document, then run: uv run doc.py"""
from kip import *

report = run_document(__file__)

# %% text scope "Scope"
"""
Describe the purpose and assumptions of this analysis.
The computed moment is @val:M, derived in @blk:moment.
"""

# %% table symbols "Nomenclature"
symbols = nomenclature({
    "P": ("Applied load", "kN"),
    "L": ("Lever arm", "mm"),
    "M": ("Bending moment", "kN m"),
})

# %% inputs inputs "Inputs"
P = 1 * kN
L = 100 * mm

# %% calc moment "Bending moment" unit=kN*m
M = P * L

# %% text conclusion "Conclusion"
"""The applied load produces a bending moment of @val:M."""
