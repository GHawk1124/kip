"""Convenience entry point for callers that just want a PDF."""
from pathlib import Path


def build_pdf(path: str | Path = "doc.py", output: str | Path | None = None,
              *, layout=None) -> Path:
    """Load, validate, execute and render; use layout.toml beside doc.py by default."""
    from .doc import build
    from .render.layout import Layout
    from .render.pdf import render

    path = Path(path).resolve()
    if path.is_dir():
        path /= "doc.py"
    if layout is None:
        sidecar = path.with_name("layout.toml")
        layout = Layout.load(sidecar) if sidecar.exists() else Layout()
    return render(build(path), output, layout=layout)
