# Simple filter / independent KISS document

Open `output/simple_filter.pdf`. The original `filter/` project is preserved.

## One-command PDF build

From the repository root:

```powershell
uv run simple_filter/generate.py
```

Or run `uv run generate.py` inside this directory. The script resolves its own
project directory, installs locked dependencies automatically, generates CAD and
hand calculations, checks Kip, and writes `output/simple_filter.pdf`. It never
rewrites the editable inputs. `regenerate.py` remains a compatibility entry point.

## Three editable workbooks

Edit the `Inputs` sheet in these files, then run the command above:

- `input/constants.xlsx`: numerical values, units, definitions and assumptions.
  The `key` column identifies values used by code. The PDF typesets those keys.
  Change values in their listed units; changing a required unit label is rejected.
- `input/requirements.xlsx`: requirement IDs, wording, assessments and targets.
  `constant_key` links to a value in constants.xlsx; `qualifier_key` supplies the
  particle size for efficiency. Use `target_text` for nonnumeric targets. Numeric
  targets are deliberately not duplicated across the workbooks.
- `input/mesh_suppliers.xlsx`: supplier rows, catalog facts, assessments, reference
  keys and URLs. These drive both mesh sourcing and the corresponding citations.

Keep the sheet name and column headers. Add or edit ordinary value rows; formulas
are rejected to avoid stale Excel calculation caches. Duplicate IDs/keys and
unknown requirement references produce explicit errors. Assessments remain
`[insert text here]` until edited. Input files are never recreated by generation.
Update water density and viscosity consistently if changing temperature.

The PDF has one long constants table without continuation headings. Mathematical
factors and exact SI conversions remain in code. All CAD dimensions and engineering
inputs come from constants.xlsx; CAD volume is derived from those dimensions.

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
Detail B uses true Build123d faces clipped to circles, with a second circle
enlarging the representative coined-frame contact. Frame thickness reduction
is read from the constants workbook; it is not a deformation simulation. Mesh CAD
solids are porous-media envelopes. `calculate.py` independently checks revolved
polygon volume against CAD. `output/calculations.json` holds the new hand results.
