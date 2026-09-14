# Simple filter / independent KISS document

Open `output/simple_filter.pdf`. The original `filter/` project is preserved.

## Edit one constants table

Edit **constants.csv** (value column) and run from this directory:

```powershell
uv sync
uv run python regenerate.py
```

The printed constants table, CAD, hand calculations, BOM and PDF regenerate from
that CSV. Editing the generated PDF does not change source data. Update water
properties consistently if changing temperature. Exact SI conversions and
mathematical factors are not tunable engineering inputs. CAD volume is derived.

## Simplification

Two identical turned cups have a conical chamber, integral titanium weld stubs,
one flat annular frame seat, and one outer rim that both limits closure and
receives the orbital butt weld. No thermal moat, root-relief groove, raised narrow
land, or separate internal stop ring. The shallow seat needed to capture the
frame remains accessible directly from the open face.

This broad seat is a geometry proposal, not a qualified crush seal. Coining force,
perimeter seam deformation, weld penetration, preload and bypass require development.
No old FEA, tolerance Monte Carlo, or thermal results are reused. Only requested
hand calculations are generated. The local cylinder check is not burst qualification.

Fine media is Dutch twill. Thickness and areal mass are explicit placeholders,
not sourced Dutch-twill specifications. GKD is the primary family lead. Haver
remains in the complete references as an alternative; HIFLO-S is not Dutch twill.
No available citation proves 99.9% at 3 um.

Named narrative sections and assessments remain `[insert text here]`. Section 08
retains the original mathematical forms; assignments reference the constants table.
Original section numbers are retained. No interpretation or old simulation figures.
Detail B is a direct Build123d section without custom plots or callouts. Mesh CAD
solids are porous-media envelopes. `calculate.py` independently checks revolved
polygon volume against CAD. `output/calculations.json` holds the new hand results.
