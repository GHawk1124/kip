"""Edit this document, then run: uv run doc.py"""
from kip import *

report = run_document(__file__)

# %% text "Scope"
"""
Describe the purpose and assumptions of this analysis.
The computed moment is @val:M, derived in @blk:moment.
"""

# %% table "Nomenclature"
nomenclature()

# %% inputs "Inputs"
P = 1 * kN  # Applied load
L = 100 * mm  # Lever arm

# %% calc moment "Bending moment"
M = P * L      # -> kN*m

# %% text "Conclusion"
"""The applied load produces a bending moment of @val:M."""
