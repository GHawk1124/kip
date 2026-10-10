---
name: kip-authoring
description: Create and edit kip engineering documents in Python, including unit-checked calculations, requirements, vector figures, tables, and PDF builds. Use for doc.py projects built with the kip CLI.
---

Use the existing project's style and requirements. For a new project run
`kip new folder` (basic), `kip new folder --template requirements` (one object
with controlled inputs and verification), or `kip new folder --template showcase`
(all features, including optional build123d CAD). Each creates a uv project,
its input workbooks under input/, and this skill. Add dependencies with
`uv add` from that folder. `kip migrate` converts an older project's
requirements.toml and sources.toml into input/ workbooks.

After every edit run `uv run kip check`. It runs and compiles the document
without writing anything and prints each problem once, as
`doc.py:LINE: error: [cell] message` with a hint: Python and unit errors (naming
the terms whose units disagree), broken references, failed checks, unverified
requirements and equations still too wide to read. Fix the first error; the
cells waiting on it are listed in one line. `layout:` notes name pages left
short. `uv run kip show` lists every cell's values and checks;
`kip check --json` and `kip show --json` give the same as data. `uv run doc.py`
regenerates CAD assets (its `prepare=`) and writes the PDF, reporting exactly
as `kip build` does. `uv run kip preview` builds and opens the PDF;
`uv run kip watch` rebuilds on source changes. Artifacts are under `output/`
beside doc.py; `--output name.pdf` chooses a filename within that folder.
Inspect rendered pages after layout edits. A build does not certify
compliance; `kip check` fails on failed checks and unverified requirements.

## Authoring

Import `from kip import *` and declare
`report = run_document(__file__, title="...", prepare=cad.generate)` above the
first marker (omit prepare without CAD). All page settings go here (see Page
layout). The first text cell wraps beneath the title automatically.
Keep editable prose in doc.py, geometry in cad.py, computations in analysis.py.
Do not generate doc.py with another Python script. Markers delimit Python blocks:

```python
# %% text "Scope"
"""Stress is @val:sigma_br; see @blk:bearing and @req:REQ-001."""

# %% inputs "Geometry"
d_pin = 32 * mm
t_plate = 16 * mm

# %% calc bearing "Bearing stress"
sigma_br = P / (d_pin * t_plate)      # -> MPa

# %% table loads "Load cases"
```

The last block is empty: it places the `loads` table built in the prelude.

Use `# %% kind "Title" key=value`; the title supplies an id such as
`"Bending moment"` -> `bending_moment`. Use `# %% kind id "Title"` for an id
that survives retitling, or `# %% kind id` for an unlabelled cell. IDs must be
unique. Kinds: text, inputs, calc, symbolic, controlled, verify, requirements,
table, plot, draw, sources, packet. Older spellings (`kip.calc id=...`, `given`,
`calculation`, `equations`, `drawing`, `references`, `unit=` on the marker)
still work but warn; do not write them.

Cells render in file order. Calculations (prelude, inputs, calc, symbolic,
controlled, verify, requirements) run top to bottom first; tables, plots,
drawings, sources and text run top to bottom after them, so prose and tables
may show values computed further down. A calculation may not read a value that
only a later calculation defines: that is an error before anything runs. A
cell whose inputs failed is BLOCKED and names what it waits on; fix the first
failure. Failures print the file:line in doc.py or analysis.py.

Units and math functions are bare names (`mm`, `kN`, `sqrt`). The one-letter
unit names (A F H J K L N V W g m s) are only units where a unit makes sense --
after a number (`9.81 * m / s**2`) or passed to a call (`x.to(m)`). Using an
undefined `H`, `L` or `g` as a variable is an error: define the variable.
Name the unit a result is read in beside the equation, as
`M = P * L    # -> kN*m`.

A calc cell is rendered from its own Python: each assignment prints as
symbolic = substituted = result. It may contain single-name assignments,
arithmetic (+ - * / **), bare function calls (`sqrt(x)` keeps units), reads such
as `C.rho_w` or `sizing.M`, `(expr).to(MPa)`, and `if`/`elif`/`else` (the
condition, unnumbered, and the taken branch are shown). Anything else -- loops, indexing,
`x if c else y`, `+=`, reassigning a name, method calls -- is refused with a
hint; compute it in the prelude or before `# equations` in an @calculation.
State every design verdict as a check, not only in prose:
`assert sigma <= sigma_allow, "Bending stress"` is shown with its values and
OK or NOT OK, takes no equation number and never stops the document; a failed
check fails `kip check`. A computed name belongs to one cell: binding it again
in any other cell is an error, so give a revised value its own name. Tables,
plots and drawings may reuse scratch names among themselves.
Values show 4 significant figures (a short typed number shows in full);
`precision=3` on a cell marker changes that cell. The result box under a calc
shows its last value; `result=sigma,MS` names the ones to show and
`result=none` hides it. An equation too wide for its column is set one step per
row; `kip check` warns about any that must still shrink.
Put setup, imports and functions in the prelude. A rich-content block uses its
last expression: `Table(...)`, `Sheet.load(...)`, `Drawing.load(...)`, `plot(...)`,
or `Sources.load(...)`. Assign only when another cell needs the object. Existing
assignments and empty cells naming an existing object remain supported.
Text blocks contain Python strings with Typst markup: `*strong*`, `_emphasis_`,
`$math$`, `$ display math $` (spaces inside), `-` bullets, `+` numbered items,
`#quote(block: true)[...]`, `#table(...)`, and references `@val:name`, `@blk:id`,
`@req:ID`, `@src:key`. Indent nested lists. Native `#list`, `#enum`, `#set`, and
`#show` work; Markdown-style `## Heading` also works. Headings inside fenced code
stay literal. Raw strings (`r"""..."""`) preserve backslash escapes; f-strings
can interpolate Python values. References inside escaped text, inline/fenced code,
comments and native Typst strings stay literal. Titles and inserted `@val:` values
are literal text. Everyday characters print as written: `bolt #4`, `<0.5 mm`,
`$45`, `~5 mm`, `a@b.com`, `8 * 2`. `*strong*` touches its words; Markdown
`**bold**` and `* item` bullets also work. A reference to an unknown value, block, source or
requirement is an error that names the closest match. An empty text block can
supply a heading without placeholder prose.

## Content

### Component packet

Use `kip new folder --template component` for a full component packet. One empty
`# %% packet component` declaration supplies the standard section order, overview,
input tables, nomenclature, requirements, references and final compliance matrix.
It binds `C` and `reqs`; do not bind those names again. Put reusable calculations
in analysis.py and call `analysis.size(C)` in a `calc` cell.

Default stages are overview, requirements, inputs, preliminary, sizing, design, analysis,
manufacturing, test, compliance. Drawings default to design; calculations, plots
and tables to analysis; inputs/controlled cells to inputs; verify cells to
compliance; prose to overview. Use `stage=sizing` etc. for placement exceptions.
Authored order is preserved within each stage. Use `section=2` for subsections.

The component scaffold creates header-only workbooks; fill the existing headers:
- constants.xlsx / Inputs: key, value, unit, description, basis, symbol, source.
- references.xlsx / Inputs: key, title, author, publisher, year, section, url, note.
- references.xlsx / Documents: description, organization, number.
- process.xlsx / Inputs: id, operation, acceptance.
- tests.xlsx / Inputs: id, requirement, procedure, criterion, result, evidence.
- requirements.xlsx: Item (id, name, kind, revision, parent, parent_file,
  description), Variables (name, value, unit, description, source) and Inputs
  (id, text, verification, parent, controls, rationale, note).

All live under input/. Never supply an older requirements.toml as well.
Reference/Document sheets are optional supporting material. Missing files and
valid header-only sheets show OPEN; unavailable inputs block dependent cells.
Test result/evidence blanks stay OPEN. PRESENT never means verified. Compliance
uses the final recorded `reqs.verify(...)` results, never inferred evidence.
Explicit exclusions use `na="manufacturing,test"` on the packet declaration
or top-level `na = ["manufacturing", "test"]` in packet.toml.
Do not put work in an excluded stage. Bad headers, units, duplicate keys and
unknown test requirement ids remain errors. `kip check` fails on required gaps.

The optional packet.toml is editable convention, not a fixed document structure:
- `order = ["overview", "preliminary", "design", "review"]` reorders/removes/adds
  sections. Use `stage=review` for custom work; reassign cells in removed stages.
- `[sections.review]` accepts `title`, `columns` (1, 2, or "default"), `required`
  (false allows visible gaps), and `generate` (false replaces generated tables
  with authored cells while retaining input validation and status reporting).
- `[defaults]` maps canonical cell kinds to stages, e.g. `calc = "preliminary"`.
- `[sheets.constants]` etc. override `path`, `sheet`, `columns`, `required`,
  `stage`, `optional`, `enabled`. Custom sheets need path, columns, stage;
  sheet defaults to Inputs. Columns are expected headers; required fields need
  nonempty row values. Built-in readers keep their essential field names.
- Removed stages stop expecting their sheets. Move a sheet's stage to retain it.
  `enabled=false` disables a reader; disabling constants/requirements also frees
  C/reqs for custom setup. Unknown settings are errors, not silent fallbacks.
- `[sheets.requirements]` configures the requirements workbook.
- `# %% packet component config="team.toml"` selects another configuration file.
  Input paths remain relative to doc.py. Build/watch reloads configuration edits.

`kip check` also compiles the Typst, without exporting a PDF or workbook, so
markup errors surface there; `--no-render` skips that step. The diagnostic
names the original cell and, for ordinary multiline prose, the source line;
generated expressions point to the cell.

### Individual content

- A `calc` cell whose only statement calls a function from analysis.py
  (`sizing = analysis.size(C)`) renders that function's `@calculation`.
  Set up its inputs before `# equations` and write ordinary straight-line
  arithmetic after that marker, one `# -> unit` per result that needs a display
  unit. `return locals()` is optional. The function call is not printed; Kip
  renders the validated arithmetic and computed values. Access results as
  attributes when the call is assigned. The equations follow the calc grammar.
- `Constants.load()` reads `input/constants.xlsx`, a `key`/`value` sheet whose
  optional `unit`, `description`, `basis`, `symbol` and `source` columns supply
  everything else. Lookups (`C.rho_w`, `C["rho_w"]`) are pint quantities, so
  never multiply a constant by a unit again; `C.value("body_d", mm)` gives a
  plain float for CAD. `C.add(...)` defines a computed constant (a property
  database, a fit) and `C.override(...)` replaces a workbook value on purpose.
  `C.table("rho_w", "mu_w")` renders any slice; `C.format("{rho_w} at {mdot_n}")`
  substitutes values into prose.
- `Sheet.load(path, constants=C, unique="id", required=("target",))` reads any
  other input sheet, interpolates `{constant}` cells, and performs the checks a
  document would otherwise write by hand. Table cells render sheets directly
  with their existing headers; `.table(...)` selects columns or adds options.
  `hide=(...)` drops columns such as keys and URLs.
  `sheet.sources(title="supplier_item")` turns catalogue rows into citations.
- References live in input/references.xlsx; `Sources.load()` reads it. Each
  `Source` field reads the column of the same name (`key`, `title`, `author`,
  `publisher`, `year`, `section`, `url`, `note`); empty cells stay absent.
  `Sources.load(a, b)` merges several workbooks.
  Standards and specifications are not references -- put them on a `Documents`
  worksheet (document description, organization, number) and render it with
  `Sheet.load("input/references.xlsx", "Documents").table()`.
- Every equation that is not definitional cites its source in the surrounding
  text with `@src:key`. Do not invent a URL, edition or table number; give the
  title, author and publisher and say in the note what is not yet pinned.
- `save_workbook(wb, path)` writes an xlsx with no creator, timestamps or tool
  identity, so a regenerated input file differs only when its data differs.
  `Table(xlsx=...)` exports already go through it.
- `read_records(path)` remains the low-level reader for a header-row worksheet;
  formulas are rejected rather than relying on stale Excel caches. Resolve
  inputs relative to doc.py.
- `Drawing.load(path)` supports SVG and PNG; `Drawing.grid([(label, drawing), ...])`
  composes views. Prefer these to project-specific XML/base64 wrappers.

- `inputs`: quantities in compact outlined boxes.
- `controlled`: assignments such as `P = reqs.P_design`, with provenance.
- `calc`: numbered numeric working; `symbolic`: SymPy expressions assigned to
  names, rendered as numbered symbolic relations.
- `table`: `Table(["Case", "Load"], [("LC-1", 10*kN)])`, or
  `Table.from_records([{"Case": "LC-1", "Load": 10*kN}])`.
  Use `Column("load", "Load", unit="kN", precision=1)` for conversion and fixed
  decimals; without `precision` a column shows significant figures. Number
  columns align right and text columns left; `align="center"` overrides.
  `xlsx="loads.xlsx"` exports every row; `max_rows=6` limits the PDF only.
  Strings are literal text. Use `Symbol("sigma_br")`, SymPy expressions, or
  `Math("sigma_y / 2")` for math cells. `Column(..., math=True)` treats that
  column's identifier strings as symbols. `Symbol` also works as a column title.
- `inputs_table(result)` builds a table from a calculation's scalar arguments and
  actual reads of Constants, Requirements and upstream results. Values, definitions,
  basis and sources are captured during the call. Pass several results to combine
  their inputs, or `C`/`reqs` for all inputs. The table can precede the calculation.
- `nomenclature()` derives the document's symbols from input, controlled and
  calculation cells, even when placed first. `nomenclature(result)` limits it to
  one calculation; `nomenclature(C)` lists constants. Metadata and direct aliases
  supply descriptions; assignment comments and single-result inline calculation
  titles fill local definitions. Missing definitions display `-`. Use
  `overrides={"sigma_br": "Bearing stress"}` for exceptions. Conflicting descriptions
  need an override; incompatible dimensions need narrower sources. Explicit
  `nomenclature({"sigma_br": ("Bearing stress", "MPa")})` remains supported.
- `plot`: `plot(xs, ys, xlabel="Thickness", ylabel="Stress")`. Sweep with
  `x = linspace(0 * m, L, 41)`: it keeps units, so `M = w * x * (L - x) / 2`
  is an array quantity, ready to plot. numpy is available as `import numpy as np`.
  Chain `.line()`, `.scatter()`, `.bar()` for more series. Quantity arrays infer
  units; `xunit`/`yunit` override them. Labels are literal strings; use `Math(...)`
  or `Symbol(...)` for mathematical labels. `Figure(...)` gives full control.
- `draw`: `Drawing(body="...CeTZ code...", width=80)`.
  Background is off; marker `panel=true` adds a tight padded panel.
- CAD: `from kip.cad import load_build123d, cad_view, cad_section, cad_face`.
  Use `bd = load_build123d()`, build a solid, then separate drawing blocks for
  `cad_view(solid, "iso")` (`top`, `side`, `front`, `bottom` also supported),
  `cad_section(solid, bd.Plane.XZ, dxf="section.dxf")`, or
  `cad_face(planar_face, dxf="face.dxf")`. The showcase is the worked example.
- `sources`: `Sources.load()`, or `Sources(book=Source(title="...",
  author="...", year=2026, url="..."))`, cited with `@src:book`.
- Requirements: load `reqs = Requirements.load()` (input/requirements.xlsx) in
  the prelude. `parent_file` on the Item row points at the parent item's
  workbook, relative to this project folder, so its variables flow down. Use `reqs.verify("REQ-001", MS, ">= 0", evidence="margin")` in the
  same table block as `matrix = compliance_matrix(reqs)`. Use
  `variables_table(reqs)` for controlled symbols and `requirements_table(reqs)`
  for the requirement listing. Do not invent evidence or material allowables.

## Page layout

Pass page settings to `run_document(__file__, ...)`: `title`, `subtitle`,
`author`, `project`, `document`, `revision`, `date`, `checker`, `client`,
`marking`, `header_left`, `header_right`, `footer_left`, `paper`, `margin`
and `grid_step` (mm), `font_size`, `grid`, `frames` (opt-in section outlines),
`section_numbering`, `columns` (1 or 2). layout.toml only holds block positions. Default layout flows automatically. First text
block `wrap_title=true` wraps alongside the metadata box. Marker `columns=2`
switches subsequent blocks to two columns; `columns=1` restores full width;
`columns=default` restores the document default. Every packet section resets to
its `[sections.id].columns` setting or the document default. For a two-column
default, use `kip new folder --columns 2` or `run_document(__file__, columns=2)`. Local switches allow part of a section to
use another width. Calculations and plots adapt to narrow columns.
Columns fill the left side first; `columnbreak=true` starts a cell in the next
column. Use it for short blocks that should sit side by side. It requires
two-column flow and keeps the cell's heading with its content.
`section=N` turns a block's label into a numbered heading: 1 a section, 2 a
subsection, 3 and beyond as deep as the document needs. Numbering, spacing and
the PDF outline follow from it, so never type section numbers into a label.
Use it on the text block that opens a section; a table's or figure's label stays
a run-in caption. `section_numbering` sets the pattern ("1.1" by
default, "I.A" for roman/letter, "" to switch numbering off).

`pagebreak=` forces a page boundary: `before` (or `true`) starts a block on a new
page, `after` ends a section on the block that closes it, `both` isolates a block.
Prefer `after` when the break belongs to the content that ends, so a heading is
never orphaned from the table it introduces. A trailing `after` adds no blank
page. A calc, inputs or symbolic cell taller than a third of a page breaks
between its equations, keeping its result with the last one; shorter cells,
plots, drawings and short tables stay whole, and `kip check` notes any page
they leave short. `snap=false` is the explicit freeform exception to grid alignment. Avoid absolute positions unless requested.
All math and drawings remain vector; retain the grid alignment built into kip.
