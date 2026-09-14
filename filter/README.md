# F100 water filter / engineering development project

Open `output/F100_engineering_design.pdf` for the engineering report.

The baseline has two identical CP titanium Grade 2 housing halves, two annealed
316L annular frames, two coarse supports and one fine-cloth candidate. It uses a
58 mm active face, 82 mm outside diameter and integral 3/4 × 0.065 inch titanium
weld stubs. Pressure requirements are 650/1300/2600 psi **inside relative to
outside**, per the user's clarification. Water temperature is 70 F.

**Development concept, not qualified for pressure service.** The fine-cloth
catalog rating does not establish 99.9% at 3 micrometers. Hydraulic coefficients,
cake resistance, coining contact behavior and weld performance need validation.
The report evaluates each requirement without converting these unknowns into
false compliance claims. Titanium stubs assume compatible titanium installation
lines; they are not directly fusion-weldable to stainless lines.

## Rebuild

Run from this directory, using the project-local environment:

```powershell
uv sync
uv run python cad_model.py
uv run python hydrostatic_fem.py
uv run python analysis.py
uv run python figures.py
uv run python author_document.py
uv run python verify_project.py
uv run kip check
uv run kip build --output F100_engineering_design.pdf
```

`kip check` reports unverified service requirements. This is intentional; the
numerical execution and consistency checks are separate and must pass.
`doc.py` is a generated, editable Kip document; `author_document.py` regenerates it.
Make persistent content changes in the author script. `requirements.toml` is
also regenerated. No Kip implementation files are modified.

## Contents

- `design.py`: shared radial housing profile and key dimensions.
- `cad_model.py`: build123d geometry, STEP/DXF/projection exports and transparent renders.
- `analysis.py`: hydraulic/cake models, selective-assembly stack and 100,000-draw sensitivity.
- `hydrostatic_fem.py`: axisymmetric elastic solver, mesh refinement and Lamé benchmark.
- `fit_mesh.py`: fits a real mesh-only CSV when measurements become available.
- `paraview_render.py`: run with ParaView `pvpython` for a transparent native render.
- `figures.py`: dimensioned explanatory drawings and Kip figure transport.
- `sources.json`: traceable supplier and method citations with explicit limits.
- `output/cad/`: assembled/exploded STEP, one housing STEP, frame blank and true section DXF.
- `output/analysis/`: JSON results, compressed Monte Carlo samples and ParaView-readable VTU.
- `assets/`: vector illustrations and transparent PNG renders.
- `output/qa/`: rendered PDF pages and review aids, not engineering evidence.

## CAD interpretation

The assembly contains exactly seven valid, noninterfering solids. Mesh discs are
**porous-media envelopes**, not metal plates and not a pore-level CAD model.
The frame blank is 0.200 mm thick; the assembled frame envelope is 0.170 mm to
represent nominal coining. Actual deformation and closed resistance seam
microstructure are process development items. Sharp profile vertices are present
in CAD/FEA; production radii and weld geometry must be resolved before release.

The thermal moat provides radial isolation only. The centered element and outer
weld have **zero axial separation**, an explicitly documented departure from the
research brief. The 60–65 micrometer selective assembly gate is geometric only;
residual contact force and bypass resistance still require validated testing.

## Numerical model boundaries

The delivered stress PNG uses PyVista/VTK. ParaView itself was not installed;
the supplied VTU and pvpython script support native ParaView rendering.
The swept 3D display derives from an axisymmetric solution, not a second 3D FEA.
There is no preload/contact, plasticity, weld defect, fatigue or woven-cloth
structural model. Sharp-corner stress peaks do not converge. Burst is unverified.

Monte Carlo distributions are analyst-selected ranges, not empirical reliability
data. The deterministic hydraulic baseline is a hypothesis pending a real
supplier curve. The NNLS recovery check is a mathematical fixture, not test data.
