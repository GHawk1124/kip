"""Create, build, inspect and preview kip documents."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

def _force_utf8() -> None:
    """Windows consoles default to cp1252, which cannot encode 'mm⁴'.

    Unit exponents and Greek letters appear in almost every kip document, so
    the CLI reconfigures its streams rather than mangling the output.  This
    must run before the Console objects below are constructed.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):  # pragma: no cover - odd terminals
                pass


_force_utf8()

app = typer.Typer(
    add_completion=False,
    help="AI-first engineering design documents: Python in, vector PDF out.",
)
console = Console()
err = Console(stderr=True)


def _fail(message: str, code: int = 1) -> None:
    err.print(f"[bold red]error[/bold red] {message}")
    raise typer.Exit(code)


def _load(path: Path, strict: bool):
    from .doc import build
    from .doc.loader import KipSyntaxError
    from .doc.validate import ValidationError
    from .doc.kernel import ExecutionError
    from .doc.graph import CycleError

    try:
        return build(path, strict=strict)
    except (KipSyntaxError, CycleError, OSError) as e:
        _fail(str(e))
    except ValidationError as e:
        for d in e.diagnostics:
            err.print(f"  {d.format(path)}")
        _fail(f"{len(e.diagnostics)} validation error(s); nothing was rendered")
    except ExecutionError as e:
        for r in e.results:
            if r.failed:
                err.print(f"  [red]{r.block_id}[/red]: {r.error}")
        _fail("document failed to execute")


def _resolve_doc(path: Path | None) -> Path:
    if path is not None:
        p = Path(path)
        if p.is_dir():
            p = p / "doc.py"
        if not p.is_file():
            _fail(f"no such document: {p}")
        return p
    for candidate in (Path("doc.py"), Path("document.py")):
        if candidate.exists():
            return candidate
    _fail("no doc.py here; pass a path or run 'kip new <name>' first")
    raise AssertionError  # unreachable


@app.command()
def new(
    name: str = typer.Argument(..., help="Project directory to create."),
    title: str = typer.Option(None, "--title", "-t", help="Document title."),
    template: str = typer.Option("basic", "--template", "-T", help="basic, requirements, or showcase (includes CAD)."),
    source: str = typer.Option(None, "--source", help="kip package path or URL; defaults to this installation's source."),
    no_sync: bool = typer.Option(False, "--no-sync", help="Skip uv sync."),
) -> None:
    """Create a ready-to-edit uv document project, including an LLM skill."""
    from .scaffold import create_project

    root = Path(name)
    try:
        files = create_project(root, title=title, template=template, source=source)
    except (ValueError, OSError) as e:
        _fail(str(e))
    console.print(f"[green]created[/green] {root}/")
    for file in files:
        console.print(f"  {file.relative_to(root.resolve())}")
    uv = shutil.which("uv")
    if not no_sync:
        if not uv:
            _fail("project created, but uv is not on PATH; install uv and run uv sync in the project")
        result = subprocess.run([uv, "sync"], cwd=root, capture_output=True, text=True)
        if result.returncode:
            err.print(result.stderr, markup=False)
            _fail("project created, but uv sync failed; correct the dependency source and run uv sync")
    console.print(f"Next: cd {root}")
    console.print("      uv run kip build")


@app.command()
def skill(
    output: Path = typer.Option(None, "--output", "-o", help="Save SKILL.md to this path instead of printing it."),
) -> None:
    """Display the bundled LLM authoring skill as plain Markdown."""
    from .resources import SKILL

    if output is None:
        typer.echo(SKILL.read_text(encoding="utf-8"))
    else:
        if output.exists():
            _fail(f"{output} already exists")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(SKILL.read_bytes())
        console.print(f"[green]wrote[/green] {output}")


@app.command()
def build(
    path: Path = typer.Argument(None, help="doc.py (default: ./doc.py)"),
    output: Path = typer.Option(None, "--output", "-o", help="PDF filename within output/ beside doc.py."),
    layout_path: Path = typer.Option(None, "--layout", help="layout.toml path."),
    flow: bool = typer.Option(False, "--flow", help="Ignore layout.toml positions."),
    dump: bool = typer.Option(False, "--dump-typst", help="Print generated Typst."),
) -> Path | None:
    """Build the document to a fully-vector PDF."""
    doc_path = _resolve_doc(path)
    from .render import emit_debug
    from .render.layout import Layout
    from .render.pdf import render

    t0 = time.perf_counter()
    document = _load(doc_path, strict=True)

    lp = Path(layout_path) if layout_path else doc_path.parent / "layout.toml"
    layout = Layout.load(lp) if lp.exists() else Layout()
    if flow:
        layout.blocks = {}

    if dump:
        typer.echo(emit_debug(document, layout))
        return

    try:
        written = render(document, output, layout=layout)
    except (ValueError, OSError) as e:
        _fail(str(e))
    dt = (time.perf_counter() - t0) * 1000

    for d in document.warnings:
        err.print(f"  [yellow]{d.format(doc_path)}[/yellow]")
    console.print(
        f"[green]built[/green] {written} "
        f"({written.stat().st_size:,} B, {len(document.ordered_blocks())} blocks, "
        f"{dt:.0f}ms)"
    )
    for name in sorted(set(document.assets.values())):
        console.print(f"        + {name}")
    return written


@app.command()
def preview(
    path: Path = typer.Argument(None, help="Document file or folder."),
    output: Path = typer.Option(None, "--output", "-o", help="PDF filename within output/."),
) -> None:
    """Build and open the PDF in the default viewer."""
    written = build(path, output, None, False, False)
    if written is not None and typer.launch(str(written)) != 0:
        _fail(f"built {written}, but could not open a PDF viewer")


@app.command()
def check(
    path: Path = typer.Argument(None, help="doc.py (default: ./doc.py)"),
) -> None:
    """Validate and execute without rendering. Exits non-zero on any error."""
    doc_path = _resolve_doc(path)
    document = _load(doc_path, strict=False)

    n_err = len(document.errors)
    n_warn = len(document.warnings)
    for d in document.diagnostics:
        style = "red" if d.severity == "error" else "yellow"
        err.print(f"  [{style}]{d.format(doc_path)}[/{style}]")

    from rich.markup import escape

    failed = [r for r in document.results.values() if r.failed]
    for r in failed:
        err.print(f"  [red]{escape(str(doc_path))}: "
                  f"{escape(r.block_id)}: {escape(r.error or '')}[/red]")

    unresolved = {k: v for k, v in document.graph.unresolved.items() if v}
    for bid, names in unresolved.items():
        err.print(f"  [yellow]{escape(str(doc_path))}: {escape(bid)}: "
                  f"undefined: {escape(', '.join(sorted(names)))}[/yellow]")

    # requirement compliance is part of the verdict: a failed or unverified
    # requirement is a failed check, not a warning
    req_failures = 0
    from kip.req import Requirements

    seen: set[int] = set()
    for value in document.namespace.values():
        if not isinstance(value, Requirements) or id(value) in seen:
            continue
        seen.add(id(value))
        passed, failed_n, unverified = value.status()
        for check in value.checks:
            if not check.passed:
                err.print(f"  [red]{escape(value.item.id)}: {escape(check.req_id)} "
                          f"FAILED: {escape(str(check.value))} "
                          f"{escape(check.criterion)}[/red]")
        for rid in unverified:
            err.print(f"  [red]{escape(value.item.id)}: {escape(rid)} "
                      f"is not verified by this document[/red]")
        req_failures += failed_n + len(unverified)
        if not failed_n and not unverified:
            console.print(
                f"[green]requirements[/green] {escape(value.item.id)}: "
                f"{passed} verified, 0 open")

    total_err = n_err + len(failed) + req_failures
    if total_err:
        _fail(f"{total_err} error(s), {n_warn} warning(s)")
    console.print(
        f"[green]ok[/green] {len(document.ordered_blocks())} blocks, "
        f"{n_warn} warning(s)"
    )


@app.command()
def show(
    path: Path = typer.Argument(None, help="doc.py (default: ./doc.py)"),
) -> None:
    """Print the block table: kind, dependencies and computed values."""
    doc_path = _resolve_doc(path)
    document = _load(doc_path, strict=False)

    table = Table(show_header=True, header_style="bold")
    for col in ("order", "id", "kind", "depends on", "defines", "value"):
        table.add_column(col)

    position = {b: i for i, b in enumerate(document.graph.order)}
    for block in sorted(document.ordered_blocks(), key=lambda b: position.get(b.id, 0)):
        result = document.results.get(block.id)
        deps = sorted(d for d in document.graph.edges[block.id] if d != "__prelude__")
        from rich.markup import escape

        from .units import fmt_quantity

        vals = escape(", ".join(
            f"{k}={fmt_quantity(v)}"
            for k, v in list((result.values if result else {}).items())[:2]
        ))
        table.add_row(
            str(position.get(block.id, "")), block.id, block.kind,
            ", ".join(deps) or "-",
            ", ".join(sorted(block.defs)[:3]) or "-",
            (vals[:44] if result and result.ok
             else f"[red]{escape(((result.error if result else None) or 'not run')[:40])}[/red]"),
        )
    console.print(table)


@app.command("layout")
def layout_cmd(
    path: Path = typer.Argument(None, help="doc.py (default: ./doc.py)"),
    auto: bool = typer.Option(False, "--auto", help="Reflow non-pinned blocks."),
    columns: int = typer.Option(None, "--columns", "-c", help="Column count."),
) -> None:
    """Inspect or regenerate layout.toml."""
    doc_path = _resolve_doc(path)
    lp = doc_path.parent / "layout.toml"
    from .render.layout import Layout, auto_layout
    from .render.pdf import measure_heights

    document = _load(doc_path, strict=True)
    lay = Layout.load(lp) if lp.exists() else Layout(path=lp)

    if not auto:
        console.print(f"[bold]{lp}[/bold] ({'freeform' if lay.freeform else 'flow'})")
        for bid, pos in lay.blocks.items():
            console.print(f"  {bid:16s} p{pos.page} x={pos.x:g}mm y={pos.y:g}mm w={pos.w:g}mm"
                          + ("  [dim]pinned[/dim]" if pos.pinned else ""))
        if not lay.blocks:
            console.print("  [dim]no positions; blocks flow in dependency order[/dim]")
        return

    # measure at the width blocks will actually occupy, then reflow
    if columns is not None:
        lay.page.columns = columns
    heights = measure_heights(document, lay.page.column_width(), layout=lay)
    auto_layout(document, lay, heights=heights, columns=columns)
    lay.save(lp)
    console.print(f"[green]wrote[/green] {lp} ({len(lay.blocks)} blocks, "
                  f"{lay.page.columns} column(s))")


def _watch_stamp(root: Path) -> str:
    """Track source and input files without watching generated artifacts or venvs."""
    digest = hashlib.blake2b(digest_size=16)
    for directory, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not d.startswith('.') and d not in {"output", "__pycache__"})
        for name in sorted(files):
            path = Path(directory) / name
            if path.suffix.lower() in {".py", ".toml", ".csv", ".xlsx", ".svg", ".dxf", ".json"}:
                digest.update(str(path.relative_to(root)).encode())
                digest.update(path.read_bytes())
    return digest.hexdigest()


@app.command()
def watch(
    path: Path = typer.Argument(None, help="doc.py (default: ./doc.py)"),
    output: Path = typer.Option(None, "--output", "-o"),
    interval: float = typer.Option(0.4, "--interval", min=0.1),
) -> None:
    """Rebuild when document sources, requirements, layout or input data change."""
    doc_path = _resolve_doc(path)
    console.print(f"[dim]watching {doc_path} (ctrl-c to stop)[/dim]")

    last: str | None = None
    while True:
        stamp = _watch_stamp(doc_path.parent)
        if stamp != last:
            last = stamp
            try:
                build(doc_path, output, None, False, False)
            except typer.Exit:
                pass
            except Exception as e:  # keep watching through errors
                err.print(f"[red]{type(e).__name__}: {e}[/red]")
        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            console.print("\n[dim]stopped[/dim]")
            return


@app.command()
def version() -> None:
    """Print versions of kip and its rendering toolchain."""
    from . import __version__
    from .math.handcalc_bridge import MITEX_VERSION
    import handcalcs, sympy, pint, typst as _typst

    console.print(f"kip       {__version__}")
    console.print(f"typst-py  {getattr(_typst, '__version__', 'unknown')}")
    console.print(f"mitex     {MITEX_VERSION} (pinned)")
    console.print(f"handcalcs {handcalcs.__version__}")
    console.print(f"sympy     {sympy.__version__}")
    console.print(f"pint      {pint.__version__}")
    console.print(f"python    {sys.version.split()[0]}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
