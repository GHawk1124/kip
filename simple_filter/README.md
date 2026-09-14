# Simple filter

From this directory, run:

```powershell
uv run doc.py
```

This prepares CAD, runs the hand calculations and writes `output/simple_filter.pdf`.
Dependencies are locked in this project; Kip is an editable local dependency.
The original `filter/` project is untouched.

## Three editable Python files

- **doc.py** — report settings and clearly marked document sections, tables,
  figures and references. Edit this directly; no script generates it.
- **cad.py** — Build123d geometry, validity/interference checks, STEP/DXF exports,
  transparent isometrics and the circular section detail.
- **analysis.py** — input validation and actual computations. Each `@calculation`
  function sets up inputs, lists equations after `# equations`, and returns
  `locals()`. Kip typesets those same equations with their computed values.

Kip supplies title wrapping, layout, drawing composition, spreadsheet reading and
PDF generation. `sources.toml` is the standard references file. Result quantities
are also written to `output/calculations.json`, grouped by calculation with units.

## Inputs

Edit the `Inputs` sheet in each workbook, preserving headers:

- `input/constants.xlsx`: values, fixed units, symbols and assumptions. CAD and
  calculations read these values. Update water properties if temperature changes.
- `input/requirements.xlsx`: wording, assessments and targets. `constant_key`
  and `qualifier_key` reference constants; `target_text` holds nonnumeric targets.
- `input/mesh_suppliers.xlsx`: sourcing rows and their reference keys and URLs.

Generation never rewrites inputs. Formulas, duplicate keys and unknown requirement
references are rejected. The constants appear as one long table in the PDF.

## Scope

Seven components: two identical turned cups, two solid frames and three directly
contacting mesh layers. Cups have integral weld stubs, a conical chamber, a flat
frame seat and one outer closure/orbital-weld rim. No thermal moat or extra relief.
The circular Detail B shows actual CAD section faces; media are envelope solids.

Narrative placeholders and original section numbers remain. Section 09 defines
assumed Dutch-twill, coarse-pair and housing resistance coefficients; section 10
is omitted and section 11 retained. Calculations are preliminary: no new FEA or
Monte Carlo, no qualified seal or burst performance, and no citation establishes
99.9% retention at 3 microns. Fine-cloth thickness and areal mass are assumptions.
