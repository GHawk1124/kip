# kip document

`doc.py` is an engineering document written in Python; `uv run doc.py` builds
it to `output/`. The authoring guide is the kip-authoring skill in
`.claude/skills/` and `.agents/skills/`; `uv run kip skill` prints it.

After every edit:

1. `uv run kip check` runs and compiles the document without writing anything.
   Every problem is one line, `doc.py:LINE: error: [cell] message`, with a
   hint where there is one. Fix the first; cells waiting on it are listed
   once, not repeated. `--json` adds every computed value.
2. `uv run kip show` lists each cell's values and checks, to confirm the
   numbers are the ones intended.
3. `uv run doc.py` regenerates any CAD assets and writes the PDF. Read the
   PDF after layout changes.

State each design verdict as a check in a calc cell, not only in prose:
`assert sigma <= sigma_allow, "Bending stress"`. A failed check fails
`kip check`.
