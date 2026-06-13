# /// script
# requires-python = ">=3.12"
# dependencies = ["kip"]
# ///
"""Cantilever bracket sizing -- kip example document.

Blocks execute in dependency order, not document order: `sizing` below is
written before the loads it depends on, and still computes correctly.
"""

from kip import *
import sympy as sp

# %% kip.text id=intro label="Purpose"
"""
# Cantilever Bracket Sizing

This document sizes a rectangular-section cantilever bracket carrying a
transverse tip load. The governing check is bending stress at the root,
compared against the material yield strength with a factor of safety.

The resulting root bending stress is @val:sigma_max against an allowable of
@val:sigma_allow, giving a margin of safety of @val:MS. See @blk:margin.
"""

# %% kip.text id=theory_note label="Method"
"""
## Governing equations

For a cantilever of length $L$ loaded by a transverse tip load $P$, the root
bending moment and the resulting peak fibre stress are:
"""

# %% kip.symbolic id=theory
P_s, L_s, M_s, c_s, I_s, b_s, h_s = sp.symbols("P L M c I b h", positive=True)
M_root = P_s * L_s
sigma_bending = M_s * c_s / I_s
I_rect = b_s * h_s**3 / 12

# %% kip.given id=loads label="Applied loading"
P = 2.5 * kN
L = 300 * mm

# %% kip.given id=geometry label="Section geometry"
b = 25 * mm
h = 40 * mm

# %% kip.given id=material label="Material: 6061-T6 aluminium"
sigma_y = 276 * MPa
FS = 1.5

# %% kip.calc id=section result_unit="I_xx=mm**4, c_out=mm" label="Second moment of area"
I_xx = b * h**3 / 12
c_out = h / 2

# %% kip.calc id=moment result_unit=kN*m label="Root bending moment"
M_max = P * L

# %% kip.calc id=sizing result_unit=MPa label="Peak bending stress"
sigma_max = M_max * c_out / I_xx

# %% kip.calc id=allowable result_unit=MPa label="Allowable stress"
sigma_allow = sigma_y / FS

# %% kip.calc id=margin label="Margin of safety"
MS = sigma_allow / sigma_max - 1

# %% kip.text id=conclusion label="Conclusion"
"""
## Result

The bracket carries the applied load with a positive margin of safety of
@val:MS, so the section is adequate. Peak stress @val:sigma_max remains below
the allowable @val:sigma_allow derived in @blk:allowable.
"""
