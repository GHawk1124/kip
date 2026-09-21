"""Rendering specimen. Build with: uv run kip build tests/fixtures/rendering"""
from kip import *

report = run_document(__file__, title="Rendering specimen", document="KIP-QA", revision="A")

# %% text "Overview"
r"""
*Strong*, _emphasis_, $sigma = P/A$, and a live value: @val:P; see @blk:load.
An escaped reference \@val:example and inline code `@val:example` stay literal.
"""

# %% table "Nomenclature"
nomenclature()

# %% inputs load "Load #1 [design]"
P = 12 * kN  # Applied load
A = 200 * mm**2  # Net area

# %% calc "Tensile stress"
sigma = P / A  # -> MPa

# %% text "Lists and native Typst" section=1
r"""
- First item
- A longer item that wraps when the document is laid out in columns, with the
  text continuing beneath the first line's text instead of beneath the bullet.
  - Nested item
  - Another nested item

+ First step
+ Second step

#strong[Native content with a value: @val:sigma.]
#text("Native string: @val:example, @src:example.")

## Code example

```typst
## A literal heading
#list([Example], [Another example])
@val:example @src:example
```

See @src:manual; punctuation is preserved.
"""

# %% plot "Literal labels"
plot([0*mm, 1*mm, 2*mm], [0*MPa, 10*MPa, 20*MPa],
     xlabel="Travel [x]", ylabel=Math('sigma "(MPa)"'), label="Case #1")

# %% table "Paginated table"
Table(["Item", "Value"], [(f"ROW-{i:03d}", i) for i in range(80)])

# %% sources "References"
Sources(manual=Source(title="Typst documentation", url="https://typst.app/docs/"))
