# kip

Write engineering documents in Python. Build vector PDFs with unit-checked
calculations, graph-paper layouts, tables, requirements and CAD drawings.

```bash
uv tool install git+https://github.com/GHawk1124/kip.git
kip new my-doc
cd my-doc
uv run doc.py
```

Edit `doc.py` directly. Put CAD in `cad.py` and optional reusable computations in
`analysis.py`. `run_document` supplies standard headers and title wrapping;
`layout.toml` is optional. Inputs and references are workbooks under `input/`. Output goes in `output/`.

- `kip new name --template requirements` starts a requirements document.
- `kip new name --template component` starts an engineering packet with standard sheets and visible gaps.
- `kip new name --template showcase` demonstrates all features, including CAD.
- `uv run kip build` builds the PDF; `uv run kip check` checks the document.
- `uv run kip check --render` also compiles Typst without writing PDF or spreadsheet exports.
- `uv run kip watch` rebuilds on changes.
- `kip skill` prints the LLM authoring guide, also included in new projects.

```python
from kip import *

report = run_document(__file__, title="Beam check", author="Engineering")

# %% text "Design intent"
"""Describe the purpose of this check."""

# %% inputs "Loads"
P = 2 * kN
L = 100 * mm

# %% calc "Bending moment"
M = P * L      # -> kN*m
```

For an external calculation, use `@calculation` in `analysis.py`:

```python
from kip import *

@calculation
def moment(P, L):
    # equations
    M = P * L      # -> kN*m
```

Then a document cell is just:

```python
# Import analysis in the document prelude.
# %% calculation "Bending moment"
analysis.moment(2 * kN, 100 * mm)
```

Setup before `# equations` is not printed. Arithmetic after it is validated and
rendered with substitutions and units, each result read in the unit its own
`# -> unit` comment names. Assign `result = analysis.moment(...)` when another
cell needs `result.M`.
Use `prepare=cad.generate` in `run_document(...)` to regenerate CAD before a direct
script build. CLI `kip build` and `kip check` consume the existing CAD assets.

## Component packets

Opt in with one declaration. The packet supplies `C` from the constants workbook
and `reqs` from the requirements file; keep these names out of your own setup.

```python
from kip import *
import analysis

report = run_document(__file__, title="Bracket")

# %% packet component

# %% text "Design intent"
"""Minimize bracket mass within the available mounting envelope."""

# %% calculation "Initial sizing" stage=sizing
sizing = analysis.size(C)

# %% draw "Front view"
Drawing.load("assets/front.svg")

# %% calculation "Strength check"
strength = analysis.strength(C)
```

The default order is **Overview, Requirements, Inputs, Preliminary Analysis,
Sizing, Design, Analysis, Manufacturing, Test, Compliance**. Authored cells retain their order
inside a section. Drawings default to Design, calculations/plots/tables to
Analysis, inputs to Inputs, and verification to Compliance. Use `stage=...` for
exceptions. `# %% preliminary "..."`, `# %% sizing "..."` and `# %% analysis "..."` are inline calculation
shorthands; decorated calls use `calculation` with `stage=sizing` when needed.

The overview, input tables, nomenclature, requirement listing and compliance
matrix are generated. `kip new --template component` creates blank starter
workbooks with these exact headers:

| File / sheet | Columns | Required row values |
|---|---|---|
| `input/constants.xlsx` / Inputs | key, value, unit, description, basis, symbol, source | key, value; units are validated, blank means dimensionless |
| `input/references.xlsx` / Inputs | key, title, author, publisher, year, section, url, note | key, title |
| `input/references.xlsx` / Documents | description, organization, number | all three |
| `input/process.xlsx` / Inputs | id, operation, acceptance | all three |
| `input/tests.xlsx` / Inputs | id, requirement, procedure, criterion, result, evidence | first four; result/evidence may remain blank |

Requirements use `requirements.toml` with the existing `[item]`, `[vars]` and
`[req]` structure. Alternatively, supply `input/requirements.xlsx` / Inputs with
`id`, `text`, `verification`; its item id defaults to the project folder name.
Choose one requirements source. Reference and applicable-document sheets are
optional supporting material; all other non-excluded sections must be present
for `kip check` to succeed.

- **PRESENT** means material exists; it is not a verification verdict.
- **OPEN** means an expected file, valid sheet's rows, section, or test result is missing.
- **BLOCKED** identifies cells whose inputs/dependencies are unavailable.
- **N/A** is explicit: `# %% packet component na="manufacturing,test"`. Supplied
  work in an excluded section is an error.
- **PASS/FAIL** in Compliance comes from recorded `reqs.verify(...)` checks.
  Having an analysis or populated test sheet never creates a passing check.

Draft packets build with OPEN/BLOCKED entries. `kip check` fails while required
work remains open or verification fails. Duplicate keys, bad headers, invalid
units, unknown test requirement ids and broken Python/Typst remain errors.
Missing drawing files are OPEN in a component packet. Packet builds re-read
workbooks and rerun authored cells so edits cannot leave cached results behind.
The basic and requirements templates retain their existing strict behavior.

### Customize the packet

Edit the optional `packet.toml` beside `doc.py`; the component starter includes
the editable default order. Only specify settings you want to change:

```toml
order = ["overview", "requirements", "inputs", "preliminary", "design", "review", "compliance"]

[sections.preliminary]
title = "Feasibility and preliminary analysis"
columns = 2

[sections.review]
title = "Design review"
required = false

[sections.inputs]
generate = false

[defaults]
calc = "preliminary"

[sheets.constants]
path = "data/loads.xlsx"
sheet = "Loads"

[sheets.risks]
path = "data/risks.xlsx"
stage = "review"
columns = ["hazard", "mitigation"]
required = ["hazard", "mitigation"]
```

`order` can reorder, remove, or add sections; `stage=review` places work in a
custom section. Removed sections stop expecting their sheets; authored cells
assigned to a removed section produce an error until reassigned. To keep a sheet
expectation, move its `stage` to a retained section. Changing a title preserves
its stage id. `[defaults]` maps canonical cell kinds to stages.

Each section accepts `title`, `columns` (1, 2, or `"default"`), `required`, and
`generate`. With `generate=false`, supply your own cells in place of generated
tables; input validation and status reporting still run. `required=false` keeps
gaps visible without requiring completion; errors and failed checks still fail.
Use a top-level `na = ["review"]` or marker `na="review"` for explicit exclusions.

Each sheet accepts `path`, `sheet` (defaults to `"Inputs"` for new sheets),
`columns` (expected headers), `required` (nonempty row values), `stage`,
`optional`, and `enabled`. Existing settings inherit their defaults; custom sheets
need `path`, `columns`, and `stage`. Built-in readers retain essential field names
such as constants' `key` and `value`. `enabled=false` removes that reader and its
expectations; disabling constants or requirements also releases `C` or `reqs`
for your own setup. Top-level `requirements_file` changes the TOML path;
`[sheets.requirements]` changes the workbook alternative. Paths are relative to
`doc.py`. To reuse another settings file, use `# %% packet component config="team.toml"`.

### One or two columns

Start with `kip new bracket --template component --columns 2`, set
`columns = 2` under `[page]` in `layout.toml`, or use
`run_document(__file__, columns=2)`. A section's `columns` setting overrides that
default. For only part of a section, switch at cell boundaries:

```python
# %% text "Working notes" stage=design columns=2
"""- First decision
- Second decision
"""

# %% draw "Full width drawing" stage=design columns=1
Drawing.load("assets/front.svg")

# %% text "Continue" stage=design columns=default
"""Back to the document's default width."""
```

The switch applies to following cells until another switch. Each packet section
starts with its own configured column count, so local changes stay within that
section. Headings and tables wrap, calculations use a narrow layout, and plots
fit the available width. The column controls also work in ordinary documents.
Flow fills the left column first. For short passages, `columnbreak=true` on a
cell starts it in the next column; use this to place two short blocks side by side.

Typst errors include the original cell location and compiler diagnostic. Ordinary
multiline prose maps back to its source line; generated expressions and text whose
line structure changed point to the authoring cell. The renderer preserves native
Typst scope while tracking these locations.

## Spreadsheet inputs

A workbook already names its columns and declares its units, so a document reads
both rather than restating them:

```python
C = Constants.load()   # input/constants.xlsx: key, value, unit, description, ...
C.rho_w                                      # 997.99 kg/m3, a pint quantity
C.value("body_d", mm)                        # 76.0, for a CAD kernel
C.add("rho_hot", CoolProp.PropsSI(...), "kg/m3", basis="CoolProp 6.6")

reqs = Sheet.load("input/requirements.xlsx", constants=C,
                  unique="id", required=("target",))
```

`Sheet` interpolates `{constant}` cells and checks the columns named by `unique=`
and `required=`. A table cell renders a `Sheet` or `Constants` directly, using
its existing headers and units. An empty cell places the object named by its id:

```python
# %% table reqs "Requirement-by-requirement assessment"
```

Or load the sheet where it belongs, with no separate assignment:

```python
# %% table "Requirements"
Sheet.load("input/requirements.xlsx", constants=C, unique="id", required=("target",))
```

Tables, plots, drawings, references and external calculations use the last
expression as their content. Existing assignments still work. A quoted title
alone supplies the block id (`"Bending moment"` becomes `bending_moment`);
keep an explicit id when references should survive a title change.

Generate supporting tables from the quantities already in use:

```python
# %% table "Flow inputs"
inputs_table(flow)

# %% calculation "Flow"
flow = analysis.flow(C)

# %% table "Nomenclature"
nomenclature()
```

`inputs_table(result)` captures scalar arguments and reads from `Constants`,
`Requirements`, and upstream calculations during the original call. It preserves
their values, definitions, basis and sources without running the calculation again.
Pass several results to combine them, or pass `C` or `reqs` for all their inputs.
Tables can precede the calculations they describe.

`nomenclature()` gathers quantities from the document's input, controlled and
calculation cells. Use `nomenclature(flow)` for one calculation, or
`nomenclature(C)` for a constants glossary. Definitions come from input metadata,
direct aliases, assignment comments and single-result inline calculation titles;
units come from the quantities. Unknown definitions display `-`. Override only
what needs clarification: `nomenclature(flow, overrides={"U_n": "Nominal velocity"})`.
Conflicting descriptions require an override; conflicting dimensions require
narrower sources. Existing `nomenclature({...})` dictionaries still work.

Text cells contain Python strings (including raw strings and f-strings) with Typst markup: `*strong*`,
`_emphasis_`, `$math$`, `-` bullets, and `+` numbered items. Native `#list(...)`,
`#enum(...)`, `#set`, and `#show` pass through. Markdown-style `## Heading`
also works. Inline/fenced code, escaped references, comments and native Typst
strings remain literal. Use `r"""..."""` when prose contains backslash escapes.
An empty text cell can supply just a section heading. Titles, plot labels and
inserted `@val:` values are literal text; use `Math(...)` or `Symbol(...)` for
mathematical plot labels.

Load Excel input rows directly with `read_records("input/constants.xlsx")`. Load SVG/PNG
views with `Drawing.load(...)`, and compose labeled views with `Drawing.grid(...)`.
All file loaders resolve relative to the document, including builds from another
working directory. Mass-flow symbols such as `mdot_n` render with an overdot.

`Sources.load("input/references.xlsx")` reads a references workbook whose
columns are the reference fields -- `key`, `title`, `author`, `publisher`,
`year`, `section`, `url`, `note`. Bind it in a `sources` cell and cite it with
`@src:key`. `[sources.key]` tables in a `sources.toml` still load, and several
files merge in one call.

Sections number themselves. `section=N` makes a block's label a heading at that
depth -- 1 a section, 2 a subsection, and as deep as you like:

```python
# %% text flow "Flow basis" section=1
# %% text coeffs "Assumed resistance coefficients" section=2
```

The numbers, the spacing and the PDF outline come from the structure, so no
number is ever typed into a label and none goes stale when a section moves.
`section_numbering` in `[page]` sets the pattern; `""` turns numbering off.

Standards and specifications are applicable documents, not references: put them
on a `Documents` worksheet with a description, an organization and a number, and
render it with `Sheet.load("input/references.xlsx", "Documents").table()`.

Generated workbooks carry no creator, timestamps or tool identity, so
regenerating an unchanged input produces identical bytes. The first text cell
wraps beneath the title by default; `wrap_title=false` opts out. Existing inline
calculations, `Sources(...)` objects and layout files remain supported.

Development: `uv sync --extra cad`, `uv run pytest`, `uv build`.
