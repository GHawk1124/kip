---
name: kip-authoring
description: Create and edit kip engineering documents in Python, including unit-checked calculations, requirements, vector figures, tables, and PDF builds. Use for doc.py projects built with the kip CLI.
---

Use the existing project's style and requirements. For a new project run
`kip new folder` (basic), `kip new folder --template requirements` (one object
with controlled inputs and verification), or `kip new folder --template showcase`
(all features, including optional build123d CAD). Each creates a uv project,
layout.toml and this skill. Add dependencies with `uv add` from that folder.

Run `uv run kip check`, then `uv run kip build`. `uv run kip preview` builds and
opens the PDF; `uv run kip watch` rebuilds on source changes. Artifacts are under
`output/` beside doc.py; `--output name.pdf` chooses a filename within that folder.
Inspect rendered pages after layout edits. Check reports failed and unverified
requirements; build validates Python execution but does not certify compliance.

## Authoring

Import `from kip import *` above the first marker. Markers delimit Python blocks:

```python
# %% text scope "Scope" wrap_title=true
"""Stress is @val:sigma_br; see @blk:bearing and @req:REQ-001."""

# %% inputs geometry "Geometry"
d_pin = 32 * mm
t_plate = 16 * mm

# %% calc bearing "Bearing stress" unit=MPa
sigma_br = P / (d_pin * t_plate)
```

Marker syntax is `# %% kind id "Optional label" key=value`. IDs are unique Python
identifiers. Old `# %% kip.calc id=bearing label="Bearing" result_unit=MPa` works.
Blocks render in file order and execute in dependency order. Assign each result
in one block; avoid hidden mutation between blocks. Units and math functions are
bare names (`mm`, `kN`, `sqrt`), not dotted calls inside calculations. For unit
conversion use `unit=MPa`, or `unit="I=mm**4, c=mm"`; avoid `.to()` in calc blocks.
Put setup, imports and functions in the prelude. Rich-content blocks must assign
their result to a variable. Text blocks contain a triple-quoted string, with
headings, Typst inline math, and references `@val:name`, `@blk:id`, `@req:ID`,
`@src:key`. A block ID and its output variable can differ.

## Content

- `inputs` (alias `given`): quantities in compact outlined boxes.
- `controlled`: assignments such as `P = reqs.P_design`, with provenance.
- `calc`: numbered numeric working; `equations` (alias `symbolic`): SymPy
  expressions assigned to names, rendered as numbered symbolic relations.
- `table`: `Table(["Case", "Load"], [("LC-1", 10*kN)])`, or
  `Table.from_records([{"Case": "LC-1", "Load": 10*kN}])`.
  Use `Column("load", "Load", unit="kN", precision=1)` for conversion/formatting.
  `xlsx="loads.xlsx"` exports every row; `max_rows=6` limits the PDF only.
  Strings are literal text. Use `Symbol("sigma_br")`, SymPy expressions, or
  `Math("sigma_y / 2")` for math cells. `Column(..., math=True)` treats that
  column's identifier strings as symbols. `Symbol` also works as a column title.
- Nomenclature is a table: `symbols = nomenclature({"sigma_br":
  ("Bearing stress", "MPa"), "MS": "Margin of safety"})`.
- `plot`: `fig = plot(xs, ys, xlabel="Thickness", ylabel="Stress")`.
  Chain `.line()`, `.scatter()`, `.bar()` for more series. Quantity arrays infer
  units; `xunit`/`yunit` override them. `Figure(...)` gives full control.
- `drawing` (alias `draw`): `drawing = Drawing(body="...CeTZ code...", width=80)`.
  Background is off; marker `panel=true` adds a tight padded panel.
- CAD: `from kip.cad import load_build123d, cad_view, cad_section, cad_face`.
  Use `bd = load_build123d()`, build a solid, then separate drawing blocks for
  `cad_view(solid, "iso")` (`top`, `side`, `front`, `bottom` also supported),
  `cad_section(solid, bd.Plane.XZ, dxf="section.dxf")`, or
  `cad_face(planar_face, dxf="face.dxf")`. The showcase is the worked example.
- `references` (alias `sources`): `refs = Sources(book=Source(title="...",
  author="...", year=2026, url="..."))`, cited with `@src:book`.
- Requirements: load `reqs = Requirements.load("requirements.toml")` in the
  prelude. Use `reqs.verify("REQ-001", MS, ">= 0", evidence="margin")` in the
  same table block as `matrix = compliance_matrix(reqs)`. Use
  `variables_table(reqs)` for controlled symbols and `requirements_table(reqs)`
  for the requirement listing. Do not invent evidence or material allowables.

## Page layout

Edit `[page]` in layout.toml: `title`, `subtitle`, `author`, `project`, `document`,
`revision`, `date`, `checker`, `marking`, `grid_step` (mm), `frames` (opt-in section
outlines), `columns` (1 or 2). Default layout flows automatically. First text
block `wrap_title=true` wraps alongside the metadata box. Marker `columns=2`
switches subsequent blocks to two columns; `columns=1` restores full width.
Use `pagebreak=true` for an intentional page start; `snap=false` is the explicit
freeform exception to grid alignment. Avoid absolute positions unless requested.
All math and drawings remain vector; retain the grid alignment built into kip.
