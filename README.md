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
`analysis.py`. `run_document(...)` holds the title, running head and every other
page setting. Inputs, requirements and references are workbooks under `input/`.
Output goes in `output/`.

- `kip new name --template requirements` starts a requirements document.
- `kip new name --template component` starts an engineering packet with standard sheets and visible gaps.
- `kip new name --template showcase` demonstrates all features, including CAD.
- `kip new name --template discovery` reports small-molecule triage and a designed
  protein binder from the files discovery tools write (needs RDKit).
- `uv run kip check` runs and compiles the document without writing a PDF or
  spreadsheet exports. It prints each problem once as
  `doc.py:LINE: error: [cell] message`, and fails on any error, broken reference,
  failed check or unverified requirement. It warns about equations still too
  wide to read and notes pages left short. `--no-render` skips compiling.
- `uv run kip show` lists every cell's values and checks; `kip check --json` and
  `kip show --json` give the same as data, for agents and scripts.
- `uv run doc.py` (or `uv run kip build`) writes the PDF and reports the same way;
  `doc.py` also runs its `prepare=` step first.
- `uv run kip watch` rebuilds on changes.
- `kip skill` prints the LLM authoring guide. New projects carry it in
  `.claude/skills` and `.agents/skills`, with the working loop in `AGENTS.md`;
  `kip skill --install .` adds or refreshes them in an existing project.
- `kip migrate` converts an older project's `requirements.toml` and `sources.toml` into `input/` workbooks.

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
# %% calc "Bending moment"
analysis.moment(2 * kN, 100 * mm)
```

Setup before `# equations` is not printed. Arithmetic after it is validated and
rendered with substitutions and units, each result read in the unit its own
`# -> unit` comment names. Assign `result = analysis.moment(...)` when another
cell needs `result.M`.
Use `prepare=cad.generate` in `run_document(...)` to regenerate CAD before a direct
script build. CLI `kip build` and `kip check` consume the existing CAD assets.

## Calculations

A calc cell is plain Python, and it is rendered from that Python: every
assignment prints as its symbolic form, the same with values substituted, and
the result, in the unit named by its `# -> unit` comment.

```python
# %% calc stress "Bending stress"
Z = b * h**2 / 6
sigma = M / Z          # -> MPa
r = sqrt(A / pi)       # sqrt keeps units: mm
if sigma > sigma_allow:
    governs = 1
else:
    governs = 0
```

A calc cell may hold single-name assignments, `+ - * / **`, bare function calls
(`sqrt`, `sin`, `exp`, `log`, `min`, `max`, `abs`, or your own), reads such as
`C.rho_w` or `sizing.M`, `(expr).to(MPa)`, and `if`/`elif`/`else`, which shows
the condition, its values and the branch taken. Anything else -- loops,
indexing, `x if c else y`, `+=`, method calls, assigning a name twice -- is
refused before the document runs, with a hint, rather than rendered as algebra
the code did not perform. Do that work in the prelude or before `# equations`.

An `assert` is a check, shown with its values and the verdict:

```python
assert sigma <= sigma_allow, "Bending stress"
# Bending stress   σ ≤ σ_allow  ⇒  12.2 MPa ≤ 160 MPa  ⇒  OK
```

A check takes no equation number and never stops the document: a failed one
prints NOT OK in red, `kip build` still writes the PDF and warns, and
`kip check` fails with the `file:line`. Checks work the same way after
`# equations` in an `@calculation`.

Values show 4 significant figures -- 12.17, 0.0025, 83333 mm³, 4.167×10⁶ -- and
a short typed number shows in full; `precision=3` on a cell marker changes it.
The result box under a calc shows its last value, or the ones named with
`result=sigma,MS` (`result=none` hides it). An equation too wide for its column
is set one step per row instead of shrinking. A calc taller than a third of a
page breaks between equations rather than leave a gap, and keeps its result
with its last row; `if` and `else` rows take no equation number.

A name a calculation computes belongs to that one cell. Binding it again in
another cell is an error naming both lines, because tables and prose built
later would otherwise show a different value from the one printed where it
was computed.

## How a document runs

Calculations (the prelude, `inputs`, `calc`, `symbolic`, `controlled`, `verify`
and `requirements` cells) run top to bottom. Tables, plots, drawings, sources
and text then run top to bottom, so the opening text, the nomenclature and a
summary table can all show values computed further down. A calculation that
reads a value only a later calculation defines is an error before anything
runs, naming both cells.

When a cell fails, the cells that depend on it are marked BLOCKED ("Waiting on
bending, which failed.") instead of failing with confusing NameErrors, and
`kip check` prints the `file:line` where the failure happened -- in `doc.py`
or in your `analysis.py`.

The one-letter unit names `A F H J K L N V W g m s` are units only where a unit
makes sense: after a number (`9.81 * m / s**2`) or passed to a call
(`x.to(m)`). Using an undefined `H`, `L` or `g` as a variable is an error,
because it would otherwise silently divide by a henry or a litre.

Cell kinds are `text`, `inputs`, `calc`, `symbolic`, `controlled`, `verify`,
`requirements`, `table`, `plot`, `draw`, `sources` and `packet`. Older spellings
still work and print a warning saying what to write instead: `# %% kip.calc
id=...`, `given`, `calculation`, `equations`, `drawing`, `references`, the
`preliminary`/`sizing`/`analysis` shorthands, and `unit=`/`result_unit=` on
the marker.

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

# %% calc "Initial sizing" stage=sizing
sizing = analysis.size(C)

# %% draw "Front view"
Drawing.load("assets/front.svg")

# %% calc "Strength check"
strength = analysis.strength(C)
```

The default order is **Overview, Requirements, Inputs, Preliminary Analysis,
Sizing, Design, Analysis, Manufacturing, Test, Compliance**. Authored cells retain their order
inside a section. Drawings default to Design, calculations/plots/tables to
Analysis, inputs to Inputs, and verification to Compliance. Use `stage=...` for
exceptions.

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
| `input/requirements.xlsx` / Item | id, name, kind, revision, parent, parent_file, description | id; one row, optional (the id defaults to the folder name) |
| `input/requirements.xlsx` / Variables | name, value, unit, description, source | name, value; optional |
| `input/requirements.xlsx` / Inputs | id, text, verification, parent, controls, rationale, note | id, text; `controls` lists variable names separated by commas |

`parent_file` points at the parent item's requirements workbook, relative to
this project folder (`../skid/input/requirements.xlsx`), so its controlled
variables flow down. An older `requirements.toml` still loads with a warning;
never supply both. Reference and applicable-document sheets are
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
for your own setup. `[sheets.requirements]` changes the requirements workbook. Paths are relative to
`doc.py`. To reuse another settings file, use `# %% packet component config="team.toml"`.

### One or two columns

Start with `kip new bracket --template component --columns 2`, or use
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

## Chemistry and biology

kip reads the files molecule generation, docking, structure prediction, protein
design and genomics tools write -- including the skills of NVIDIA's BioNeMo Agent
Toolkit -- and shows them with units and checks like any other calculation.
`kip new name --template discovery` is a worked hit-triage and binder-design report.
Molecules use RDKit (`uv add rdkit`, or install `kip[chem]`); sequences, alignments,
structures and variants need nothing extra.

```python
hits = read_molecules("input/candidates.csv")      # or DiffDock .sdf, GenMol .json, .smi
model = Structure.load("input/binder_complex.cif")  # PDB or mmCIF
lead = hits.get("GM-002")

# %% table candidates "Candidates"
molecule_table(hits, "qed", "mass", "pic50", passes=lambda m: m.pic50 >= 6)

# %% calc lead_checks "Lead candidate"
IC50 = 10 ** (-lead.pic50) * molar   # -> nM
MW = lead.mass                       # -> g/mol
assert MW <= 500 * g / mol, "Rule of five: mass"

# %% draw complex "Co-folded complex"
model                                # backbone coloured by pLDDT, with a link to the file
```

- `read_molecules` keeps every column or SD tag as a property (`m.pic50`), and
  computes `mass`, `exact_mass`, `logp`, `tpsa`, `qed`, `hbd`, `hba` and
  `rule_of_five`. A molecule in a draw cell shows its ACS-style structure; in a
  table cell, its structure at a common scale; `molecule_grid` draws a series.
- `read_fasta` gives sequences by name with header `key=value` scores; a
  `Sequence` has `mass`, `gc`, `extinction()`, `translate()`, `identity()` and
  `mutations()`, and a draw cell shows a numbered listing with marked positions.
- `Structure` reads chains, sequences, per-residue pLDDT, ligands, interface
  residues and superposed RMSD. `read_a3m`, `read_vcf` with `variant_table`, and
  `read_json` (scores with attribute access) cover alignments, variants and
  model confidence files.
- Concentrations (`nM`, `uM`, `molar`), masses (`Da`, `kDa`), `angstrom`,
  `kcal`, `uL` and `ng` are units like any other.

## Electronics

kip reads what electronics tools write: SPICE netlists and results, schematics,
boards and the fabrication files plotted from them, HDL and simulation dumps,
FPGA reports, S-parameters, field-solver models and chip layouts. Each one can
be drawn, tabulated, or checked against the design.
`kip new name --template circuit` takes an active filter from the schematic
through simulation to Gerber files. `kip new name --template fpga` takes a UART
from Verilog to timing closure. Simulation needs ngspice on the PATH (or
`KIP_NGSPICE`). The readers need nothing extra, except that schemdraw drawings
need `kip[electronics]`, which both templates install.

```python
net = read_netlist("input/filter.cir")       # kicad-cli sch export netlist --format spice
board = Board.load("input/filter.kicad_pcb")
fab = read_gerbers("input/fab.zip")          # Gerber and Excellon files

def response(R, C):
    """Output over input, simulated with these values (or read from the cache)."""
    sim = simulate(net.with_values(R1=R, C1=C), cache="input/filter.raw")
    return sim.ac.v("out") / sim.ac.v("in")

# %% inputs design "Design inputs"
f_0 = 1 * kHz
C = 10 * nF

# %% calc sim "Simulated response"
R = standard_value(1 / (2 * pi * f_0 * C), 96)   # -> kohm
H = response(R, C)
f_sim = cutoff(H)                                 # -> kHz
assert abs(f_sim - f_0) <= 0.02 * f_0, "Corner within 2 % of the design"

# %% calc fab_checks "Fabrication checks"
supply = trace_width(I=0.25 * A, dT=10 * K, t=35 * um)
assert board.min_track >= supply.w, "Tracks carry the supply current"
assert fab.min_drill >= 0.3 * mm, "Smallest hole within the fabricator's limit"
```

Calc cells call functions and read attributes, but do not call methods or
index, so `sim.ac.v("out")` or `placed["LUT"]` goes in a prelude function or
name. The simulation then follows the inputs: change `C`
and the next build runs ngspice again.

- SPICE: `read_netlist` reads ngspice, LTspice and KiCad netlists. `simulate`
  runs ngspice and caches the results next to the document, so builds without
  ngspice and builds on other machines read the cache while the netlist is
  unchanged. `read_raw` reads ngspice, Xyce and LTspice results. A `Signal` has
  measurement functions (`cutoff`, `phase_margin`, `rise_time`, `overshoot`,
  `settling_time`, `rms`, ...), and a plot cell draws an AC response as a Bode
  plot. `standard_value(x, 96)` gives the nearest E96 value.
- Schematics: KiCad (`.kicad_sch`, with its sheets) and xschem (`.sch`, with
  stand-in symbols when the libraries are absent) draw as vector figures with
  the source file attached; a KiCad `bom()` groups parts by value. KiCad netlists,
  SKiDL circuits and schemdraw drawings work too.
- Boards: a KiCad board gives size, layers, track widths and lengths, holes and
  placement; it draws as fabricated (top, bottom, or copper only).
  `read_gerbers` reads the fabrication files back (a zip, a folder or a list) to
  check them against the board. `read_drill`, `read_bom` and `read_placement`
  read single files. `trace_width` (IPC-2221), `microstrip` and `stripline` are
  calculations that render their equations.
- HDL and FPGA: `read_hdl` (Verilog, SystemVerilog, VHDL) gives ports,
  parameters and a block symbol. `read_vcd` gives traces with edge, pulse and
  period measurements, plus timing diagrams; `wavedrom` draws WaveDrom
  specifications. `read_utilization`, `read_timing` (with `fmax`) and
  `read_constraints` read Vivado, Quartus, Yosys, nextpnr and OpenSTA output.
- RF: `read_touchstone` gives S-parameters with return loss, VSWR, impedance,
  resonance, bandwidth and group delay, and draws a Smith chart.
  `polar_pattern` draws antenna patterns, and `read_csx` reads an openEMS model
  with its mesh.
- Chip layout: `read_gds` (sky130 layer names, or a KLayout `.lyp`) and
  `read_magic` draw layouts and tabulate layers. `read_metrics` reads OpenLane
  and LibreLane run metrics.

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
mathematical plot labels. Characters that cannot be the markup the author meant
print as written -- `bolt #4`, `<0.5 mm`, `$45`, `~5 mm`, `a@b.com`, `C:\temp`,
`8 * 2` -- while `#strong[...]`, `*bold*`, `$x$`, `Fig.~3` and a referenced
`<label>` keep their Typst meaning. Markdown `**bold**` and `* item` bullets
mean what they do in Markdown. An `@val:`, `@blk:`, `@src:` or `@req:` reference to something
the document does not define is an error that suggests the closest match.

Sweep a plot with `x = linspace(0 * m, L, 41)`: it keeps units, so
`plot(x, w * x * (L - x) / 2)` labels both axes. numpy is installed with kip.

Load Excel input rows directly with `read_records("input/constants.xlsx")`. Load SVG/PNG
views with `Drawing.load(...)`, and compose labeled views with `Drawing.grid(...)`.
All file loaders resolve relative to the document, including builds from another
working directory. Mass-flow symbols such as `mdot_n` render with an overdot.

`Sources.load()` reads `input/references.xlsx`, whose columns are the
reference fields -- `key`, `title`, `author`, `publisher`, `year`, `section`,
`url`, `note`. Put it in a `sources` cell and cite with `@src:key`. Several
workbooks merge in one call: `Sources.load(a, b)`.

Sections number themselves. `section=N` makes a block's label a heading at that
depth -- 1 a section, 2 a subsection, and as deep as you like:

```python
# %% text flow "Flow basis" section=1
# %% text coeffs "Assumed resistance coefficients" section=2
```

The numbers, the spacing and the PDF outline come from the structure, so no
number is ever typed into a label and none goes stale when a section moves.
`run_document(..., section_numbering="I.A")` sets the pattern; `""` turns numbering off.

Standards and specifications are applicable documents, not references: put them
on a `Documents` worksheet with a description, an organization and a number, and
render it with `Sheet.load("input/references.xlsx", "Documents").table()`.

Generated workbooks carry no creator, timestamps or tool identity, so
regenerating an unchanged input produces identical bytes. The first text cell
wraps beneath the title by default; `wrap_title=false` opts out. `layout.toml`
holds only freeform block positions written by `kip layout --auto`.

Development: `uv sync --extra cad`, `uv run pytest`, `uv build`.
