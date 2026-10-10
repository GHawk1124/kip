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
# Soft wrap: a long path or message stays on one line for whoever parses it.
console = Console(soft_wrap=True)
err = Console(stderr=True, soft_wrap=True)


def _fail(message: str, code: int = 1) -> None:
    err.print("error " + message, style="red", markup=False, soft_wrap=True)
    raise typer.Exit(code)


def _load(path: Path, strict: bool):
    from .doc import build
    from .doc.loader import KipSyntaxError
    from .doc.validate import ValidationError
    from .doc.kernel import ExecutionError
    try:
        return build(path, strict=strict)
    except (KipSyntaxError, OSError) as e:
        _fail(str(e))
    except ValidationError as e:
        for d in e.diagnostics:
            err.print(f"  {d.format(path)}", markup=False)
        _fail(f"{len(e.diagnostics)} validation error(s); nothing was rendered")
    except ExecutionError as e:
        _print_failures(e.results, path)
        _fail("document failed to execute")


def _print_failures(results, doc_path: Path) -> int:
    """Each failed cell at the file:line where it failed, then the cells it blocked."""
    from .doc.kernel import where

    failed = [r for r in results if r.failed]
    for r in failed:
        err.print(f"  {where(r) or doc_path}: error: [{r.block_id}] {r.error or ''}",
                  style="red", markup=False)
    waiting = [r.block_id for r in results
               if r.state == "BLOCKED" and r.reason.startswith("Waiting on")]
    if waiting:
        err.print(f"  blocked until that is fixed: {', '.join(waiting)}",
                  style="yellow", markup=False)
    return len(failed)


def _warn_failed_checks(document, doc_path: Path) -> None:
    """A failed ``assert`` does not stop a build; it is shown, and named here."""
    for result in document.results.values():
        for check in result.assertions:
            if not check.passed:
                err.print(f"  {check.file or doc_path}:{check.line}: warning: "
                          f"[{result.block_id}] check failed: {check.describe()}",
                          style="yellow", markup=False)


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
    template: str = typer.Option("basic", "--template", "-T", help="basic, requirements, component, showcase (includes CAD), or discovery (chemistry and biology)."),
    columns: int = typer.Option(None, "--columns", "-c", min=1, max=2, help="Default page columns (1 or 2)."),
    source: str = typer.Option(None, "--source", help="kip package path or URL; defaults to this installation's source."),
    no_sync: bool = typer.Option(False, "--no-sync", help="Skip uv sync."),
) -> None:
    """Create a ready-to-edit uv document project, including an LLM skill."""
    from .scaffold import create_project

    root = Path(name)
    try:
        files = create_project(root, title=title, template=template, source=source, columns=columns)
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
    console.print("      uv run doc.py")


@app.command()
def skill(
    output: Path = typer.Option(None, "--output", "-o", help="Save SKILL.md to this path instead of printing it."),
    install: Path = typer.Option(None, "--install", help="Install or refresh the skill in this project folder "
                                 "(.claude/skills and .agents/skills), adding AGENTS.md and CLAUDE.md if missing."),
) -> None:
    """Display the bundled LLM authoring skill as plain Markdown."""
    from .resources import SKILL

    if install is not None:
        from .scaffold import install_guide
        if not install.is_dir():
            _fail(f"no such folder: {install}")
        for written in install_guide(install):
            console.print(f"[green]wrote[/green] {written}")
        return
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
        err.print(f"  {d.format(doc_path)}", style="yellow", markup=False)
    _warn_failed_checks(document, doc_path)
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
    render: bool = typer.Option(True, "--render/--no-render",
                                help="Compile the Typst too (no PDF or exports are written); "
                                     "--no-render skips it for a faster check."),
    as_json: bool = typer.Option(False, "--json",
                                 help="Print problems, layout notes and every cell's values as JSON."),
) -> None:
    """Validate, execute and compile without writing anything. Exits non-zero on any error."""
    import json

    from . import report
    from .doc.kernel import _all_requirements

    doc_path = _resolve_doc(path)
    if as_json:
        from .doc import build
        from .doc.loader import KipSyntaxError
        try:
            document = build(doc_path, strict=False)
        except KipSyntaxError as e:  # a marker kip cannot read: still answer in JSON
            problem = report.Problem("error", e.args[0], file=e.path, line=e.lineno)
            typer.echo(json.dumps({"document": str(doc_path), "ok": False, "errors": 1,
                                   "warnings": 0, "problems": [problem.__dict__],
                                   "notes": [], "blocks": []}, ensure_ascii=False, indent=1))
            raise typer.Exit(1)
    else:
        document = _load(doc_path, strict=False)
    found = report.problems(document, doc_path)
    notes: list[str] = []
    if render and not document.errors and not any(r.failed for r in document.results.values()):
        from .render.layout import Layout
        sidecar = doc_path.parent / "layout.toml"
        layout = Layout.load(sidecar) if sidecar.exists() else Layout()
        laid_out, notes = report.layout(document, doc_path, layout)
        found += laid_out
    errors = sum(p.severity == "error" for p in found)
    warnings = len(found) - errors

    if as_json:
        typer.echo(json.dumps(report.as_json(document, doc_path, found, notes),
                              ensure_ascii=False, indent=1))
        if errors:
            raise typer.Exit(1)
        return

    for problem in found:
        err.print("  " + problem.format(), markup=False,
                  style="red" if problem.severity == "error" else "yellow")
        if problem.detail:
            err.print(problem.detail, style="dim", markup=False)
    waiting = [r.block_id for r in document.results.values()
               if r.state == "BLOCKED" and r.reason.startswith("Waiting on")]
    if waiting:
        err.print(f"  blocked until that is fixed: {', '.join(waiting)}",
                  style="yellow", markup=False)
    for note in notes:
        console.print(f"  layout: {note}", style="dim", markup=False)
    for reqs in _all_requirements(document.namespace):
        passed, failed_n, unverified = reqs.status()
        if not failed_n and not unverified:
            console.print(f"[green]requirements[/green] {reqs.item.id}: {passed} verified, 0 open",
                          highlight=False)
    checks = [c for r in document.results.values() for c in r.assertions]
    if checks and all(c.passed for c in checks):
        console.print(f"[green]checks[/green] {len(checks)} passed")
    if errors:
        _fail(f"{errors} error(s), {warnings} warning(s)")
    console.print(f"[green]ok[/green] {len(document.ordered_blocks())} blocks, "
                  f"{warnings} warning(s)")


@app.command()
def show(
    path: Path = typer.Argument(None, help="doc.py (default: ./doc.py)"),
    as_json: bool = typer.Option(False, "--json", help="Print the cells as JSON."),
) -> None:
    """Print every cell's state, computed values and checks."""
    import json

    from . import report

    doc_path = _resolve_doc(path)
    document = _load(doc_path, strict=False)
    entries = report.blocks(document)
    if as_json:
        typer.echo(json.dumps(entries, ensure_ascii=False, indent=1))
        return
    for entry in entries:
        label = f' "{entry["label"]}"' if entry["label"] else ""
        console.print(f"{entry['kind']} {entry['id']}{label}  {doc_path}:{entry['line']}",
                      style="bold", markup=False, highlight=False)
        if entry["state"] == "failed":
            console.print(f"  FAILED: {entry['error']}", style="red", markup=False)
        elif entry["state"] != "ok":
            console.print(f"  {entry['state'].upper()}: {entry.get('reason', '')}",
                          style="yellow", markup=False)
        for name, value in entry["values"].items():
            console.print(f"  {name} = {value['text']}", markup=False, highlight=False)
        for c in entry.get("checks", []):
            what = f" ({c['message']})" if c["message"] else ""
            console.print(f"  check {c['condition']}{what}: {'OK' if c['passed'] else 'NOT OK'}",
                          markup=False, highlight=False,
                          style=None if c["passed"] else "red")
        if entry["uses"]:
            console.print(f"  uses {', '.join(entry['uses'])}", style="dim", markup=False)


@app.command("layout")
def layout_cmd(
    path: Path = typer.Argument(None, help="doc.py (default: ./doc.py)"),
    auto: bool = typer.Option(False, "--auto", help="Reflow non-pinned blocks."),
    columns: int = typer.Option(None, "--columns", "-c", min=1, max=2, help="Column count."),
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
def migrate(
    path: Path = typer.Argument(Path("."), help="Project folder (default: here)."),
) -> None:
    """Convert requirements.toml and sources.toml into input/ workbooks."""
    from .migrate import migrate as convert

    try:
        done = convert(Path(path))
    except (OSError, ValueError) as e:
        _fail(str(e))
    if not done:
        console.print("nothing to migrate")
    for old, new in done:
        console.print(f"[green]wrote[/green] {new}  (kept {old.name}.bak)")


@app.command()
def version() -> None:
    """Print versions of kip and its rendering toolchain."""
    from . import __version__
    import sympy, pint, typst as _typst

    console.print(f"kip       {__version__}")
    console.print(f"typst-py  {getattr(_typst, '__version__', 'unknown')}")
    console.print(f"sympy     {sympy.__version__}")
    console.print(f"pint      {pint.__version__}")
    console.print(f"python    {sys.version.split()[0]}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
