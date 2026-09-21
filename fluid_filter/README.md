# F200 fluid filter

Run `uv run doc.py` here to regenerate CAD, sweeps and `output/fluid_filter.pdf`.
The seven-piece titanium / stainless concept and pressure / flow requirements
come from F100. This is a separate component project.

Edit `input/design.xlsx`:

- **Inputs** — units, fluid density / viscosity / temperature, geometry and targets.
  OD and wall drive the inlet and outlet. ID is always derived as OD − 2 wall.
- **Calibration** — one finished-pack coefficient pair per micron rating. Blank
  coefficients or missing evidence leave that rating OPEN. Enter Cv in 1/m,
  Ci dimensionless, and replace the OPEN evidence text with a test / supplier reference.
- **ReferenceScreens** — the three published Dutch-twill cases. Da is measured
  average capillary diameter, never filtration rating. These rows remain sensitivities.
- **Sweeps** — numeric sweep points with units. Pressure factors multiply the
  specified proof / burst pressures. Geometry sweeps change one input at a time.
- **Process / Tests / References** — planned work and its sources. Empty test
  results and evidence remain OPEN; a spreadsheet entry does not automatically certify a requirement.

Change `fluid.toml` for fluid identity and state assumptions. Change density,
viscosity and temperature together in the workbook. The constant-property,
single-phase Newtonian model requires review for gas compressibility, phase
changes and material compatibility.

`doc.py` is the report: section prose, the drawings, and one cell per
calculation. `analysis.py` holds the equations. Kip typesets the arithmetic
after each `# equations` line, so the PDF shows the substitution rather than a
summary table of the same result. `cad.py` builds the seven-solid assembly.
`packet.toml` sets the section order and titles. The page is one column.

Clean loss uses Cv μ U + Ci ρ U² with U = mass flow / (density × exposed area).
Calibrate the finished pack, including supports, with `fit_coefficients` or
enter supplier coefficients. Housing loss K ρ V² / 2 is separate. Inlet curves
use the largest illustrative K in the sweep sheet and label it. The complete K
sensitivity appears in the inlet table. Clean and loaded loss limits apply at
nominal flow; the inherited design has no separate surge loss limit.

Blockage and cake curves are separate idealizations. Neither establishes dirt
capacity or efficiency. Proof / burst plots are elastic local cylinder screens;
cone, weld, fatigue and blocked-media strength remain unqualified.

Exports: `output/sweeps.csv`, `output/cad/fluid_filter.step`,
`output/cad/housing_half.step`, `output/cad/axial_section.dxf` and CAD checks.
