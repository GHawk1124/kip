---
name: kip-authoring
description: Create and edit kip engineering documents in Python, including unit-checked calculations, requirements, vector figures, tables, and PDF builds. Use for doc.py projects built with the kip CLI.
---

Use the existing project's style and requirements. For a new project run
`kip new folder` (basic), `kip new folder --template requirements` (one object
with controlled inputs and verification), or `kip new folder --template showcase`
(all features, including optional build123d CAD). Each creates a uv project,
layout.toml and this skill. Add dependencies with `uv add` from that folder.

Run `uv run doc.py` to prepare assets and build. `uv run kip check` validates
existing assets; `uv run kip build` also remains supported. `uv run kip preview` builds and
opens the PDF; `uv run kip watch` rebuilds on source changes. Artifacts are under
`output/` beside doc.py; `--output name.pdf` chooses a filename within that folder.
Inspect rendered pages after layout edits. Check reports failed and unverified
requirements; build validates Python execution but does not certify compliance.

## Authoring

Import `from kip import *` and declare
`report = run_document(__file__, title="...", prepare=cad.generate)` above the
first marker (omit prepare without CAD). Page metadata can be passed here;
layout.toml is optional. The first text cell wraps beneath the title automatically.
Keep editable prose in doc.py, geometry in cad.py, computations in analysis.py.
Do not generate doc.py with another Python script. Markers delimit Python blocks:

```python
# %% text scope "Scope"
"""Stress is @val:sigma_br; see @blk:bearing and @req:REQ-001."""

# %% inputs geometry "Geometry"
d_pin = 32 * mm
t_plate = 16 * mm

# %% calc bearing "Bearing stress"
sigma_br = P / (d_pin * t_plate)      # -> MPa

# %% table loads "Load cases"
```

The last block is empty: it places the `loads` table built in the prelude.

Marker syntax is `# %% kind id "Optional label" key=value`. IDs are unique Python
identifiers. Old `# %% kip.calc id=bearing label="Bearing" result_unit=MPa` works.
Blocks render in file order and execute in dependency order. Assign each result
in one block; avoid hidden mutation between blocks. Units and math functions are
bare names (`mm`, `kN`, `sqrt`), not dotted calls inside calculations. Name the
unit a result is read in beside the equation, as `M = P * L    # -> kN*m`; avoid
`.to()` in calc blocks (`unit=MPa` on the marker still works).
Put setup, imports and functions in the prelude. A rich-content block either
assigns its object or is empty, in which case it places the object already bound
to the block's own id -- so a table built in the prelude needs only its marker
line. Text blocks contain a triple-quoted string, with
headings, Typst inline math, and references `@val:name`, `@blk:id`, `@req:ID`,
`@src:key`. A block ID and its output variable can differ.

## Content

- `calculation`: bind a function decorated with `@calculation` from analysis.py.
  Set up its inputs before `# equations` and write ordinary straight-line
  arithmetic after that marker, one `# -> unit` per result that needs a display
  unit. `return locals()` is optional. The function call is not printed; Kip
  renders the validated arithmetic and computed values. Access results as
  attributes. Use this kind for dotted calls; inline `calc` retains its stricter
  syntax checks.
- `Constants.load("input/constants.xlsx")` reads a `key`/`value` sheet whose
  optional `unit`, `description`, `basis`, `symbol` and `source` columns supply
  everything else. Lookups (`C.rho_w`, `C["rho_w"]`) are pint quantities, so
  never multiply a constant by a unit again; `C.value("body_d", mm)` gives a
  plain float for CAD. `C.add(...)` defines a computed constant (a property
  database, a fit) and `C.override(...)` replaces a workbook value on purpose.
  `C.table("rho_w", "mu_w")` renders any slice; `C.format("{rho_w} at {mdot_n}")`
  substitutes values into prose.
- `Sheet.load(path, constants=C, unique="id", required=("target",))` reads any
  other input sheet, interpolates `{constant}` cells, and performs the checks a
  document would otherwise write by hand. `sheet.table()` renders it with the
  header row as column titles; `hide=(...)` drops columns such as keys and URLs.
  `sheet.sources(title="supplier_item")` turns catalogue rows into citations.
- References use `Sources.load("sources.toml", "input/suppliers.xlsx")`, which
  merges `[sources.key]` tables and `key`/`title`/`url`/`note` sheets.
- `read_records(path)` remains the low-level reader for a header-row worksheet;
  formulas are rejected rather than relying on stale Excel caches. Resolve
  inputs relative to doc.py.
- `Drawing.load(path)` supports SVG and PNG; `Drawing.grid([(label, drawing), ...])`
  composes views. Prefer these to project-specific XML/base64 wrappers.

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
