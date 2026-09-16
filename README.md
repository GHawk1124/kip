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
- `kip new name --template showcase` demonstrates all features, including CAD.
- `uv run kip build` builds the PDF; `uv run kip check` checks the document.
- `uv run kip watch` rebuilds on changes.
- `kip skill` prints the LLM authoring guide, also included in new projects.

```python
from kip import *

report = run_document(__file__, title="Beam check", author="Engineering")

# %% text scope "Design intent"
"""Describe the purpose of this check."""

# %% inputs loads "Loads"
P = 2 * kN
L = 100 * mm

# %% calc moment "Bending moment"
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
# %% calculation moment "Bending moment"
result = analysis.moment(2 * kN, 100 * mm)
```

Setup before `# equations` is not printed. Arithmetic after it is validated and
rendered with substitutions and units, each result read in the unit its own
`# -> unit` comment names. Results are available as `result.M`.
Use `prepare=cad.generate` in `run_document(...)` to regenerate CAD before a direct
script build. CLI `kip build` and `kip check` consume the existing CAD assets.

## Spreadsheet inputs

A workbook already names its columns and declares its units, so a document reads
both rather than restating them:

```python
C = Constants.load("input/constants.xlsx")   # key, value, unit, description, ...
C.rho_w                                      # 997.99 kg/m3, a pint quantity
C.value("body_d", mm)                        # 76.0, for a CAD kernel
C.add("rho_hot", CoolProp.PropsSI(...), "kg/m3", basis="CoolProp 6.6")

reqs = Sheet.load("input/requirements.xlsx", constants=C,
                  unique="id", required=("target",))
```

`Sheet` interpolates `{constant}` cells, checks the columns named by `unique=`
and `required=`, and renders itself with `sheet.table()` -- titled from its own
header row, so a table that lives in a spreadsheet stays there. A content cell
with an empty body places the object already bound to the cell's id:

```python
# %% table reqs "Requirement-by-requirement assessment"
```

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
