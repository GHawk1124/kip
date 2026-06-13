# kip

Write engineering documents in Python. Build vector PDFs with unit-checked
calculations, graph-paper layouts, tables, requirements and CAD drawings.

```bash
uv tool install git+https://github.com/GHawk1124/kip.git
kip new my-doc
cd my-doc
uv run kip preview
```

Edit `doc.py` for content and `layout.toml` for page settings. Generated files
are saved in `output/`.

- `kip new name --template requirements` starts a requirements document.
- `kip new name --template showcase` demonstrates all features, including CAD.
- `uv run kip build` builds the PDF; `uv run kip check` checks the document.
- `uv run kip watch` rebuilds on changes.
- `kip skill` prints the LLM authoring guide, also included in new projects.

```python
from kip import *

# %% inputs loads "Loads"
P = 2 * kN
L = 100 * mm

# %% calc moment "Bending moment" unit=kN*m
M = P * L
```

Development: `uv sync --extra cad`, `uv run pytest`, `uv build`.
