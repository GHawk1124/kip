"""Create document projects from the same resources in source and wheel installs."""
from __future__ import annotations

import json
import re
import shutil
from importlib.metadata import distribution
from pathlib import Path

import tomlkit

from .resources import SKILL, TEMPLATES


def dependency(source: str | None = None, *, cad: bool = False) -> str:
    """Retain a local/VCS installation's source instead of guessing a PyPI release."""
    dist = distribution("kip")
    if source is None:
        direct = json.loads(dist.read_text("direct_url.json") or "{}")
        source = direct.get("url")
        vcs = direct.get("vcs_info")
        if vcs:
            source = f"{vcs['vcs']}+{source}@{vcs['commit_id']}"
        if source and direct.get("subdirectory"):
            source += f"#subdirectory={direct['subdirectory']}"
    if source and Path(source).exists():
        source = Path(source).resolve().as_uri()
    name = "kip[cad]" if cad else "kip"
    return f"{name} @ {source}" if source else f"{name}=={dist.version}"


def create_project(root: Path, *, title: str | None = None,
                   template: str = "basic", source: str | None = None,
                   columns: int | None = None) -> list[Path]:
    """Populate an empty directory. Never overwrite an existing project.

    Templates keep their inputs as readable TOML in kip's source tree; a new
    project receives them as the workbooks under ``input/`` that kip reads,
    and its page settings in ``run_document(...)`` at the top of doc.py.
    """
    import tomllib

    from .migrate import references_workbook, requirements_workbook
    from .render.layout import PageSpec

    if columns is not None:
        PageSpec(columns=columns)  # Validate before writing any files.
    available = sorted(p.name for p in TEMPLATES.iterdir() if p.is_dir())
    if template not in available:
        raise ValueError(f"unknown template {template!r}; choose {', '.join(available)}")
    if root.exists() and (not root.is_dir() or any(root.iterdir())):
        raise ValueError(f"{root} already exists and is not empty")
    root = root.resolve()
    slug = re.sub(r"[^a-z0-9]+", "-", root.name.lower()).strip("-") or "document"
    doc_title = title or root.name.replace("-", " ").replace("_", " ").title()
    requirement = dependency(source, cad=template == "showcase")
    root.mkdir(parents=True, exist_ok=True)
    for file in (TEMPLATES / template).iterdir():
        if not file.is_file():
            continue
        if file.name == "requirements.toml":
            data = tomllib.loads(file.read_text(encoding="utf-8"))
            if template == "component":
                data["item"].update(id=slug.upper(), name=doc_title)
            requirements_workbook(data, root / "input" / "requirements.xlsx")
        elif file.name == "sources.toml":
            data = tomllib.loads(file.read_text(encoding="utf-8"))
            references_workbook(data.get("sources", {}), root / "input" / "references.xlsx")
        else:
            shutil.copyfile(file, root / file.name)
    if template == "component":
        from .packet import create_inputs
        create_inputs(root)
    _page_settings(root / "doc.py", title=doc_title if title or template != "showcase" else None,
                   columns=columns)
    pyproject = tomlkit.document()
    pyproject["project"] = {"name": slug, "version": "0.1.0",
                            "description": doc_title, "requires-python": ">=3.12",
                            "dependencies": [requirement]}
    pyproject["tool"] = {"uv": {"package": False}}
    (root / "pyproject.toml").write_text(tomlkit.dumps(pyproject), encoding="utf-8")
    (root / ".python-version").write_text("3.12\n", encoding="utf-8")
    (root / ".gitignore").write_text(".venv/\n__pycache__/\noutput/\n", encoding="utf-8")
    skill = root / ".agents" / "skills" / "kip-authoring" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_bytes(SKILL.read_bytes())
    return sorted(p for p in root.rglob("*") if p.is_file())


def _page_settings(doc: Path, *, title: str | None, columns: int | None) -> None:
    """Put the title (and a column default) into the template's run_document call."""
    text = doc.read_text(encoding="utf-8")
    call = "run_document(__file__"
    if call not in text:
        return
    extra = ""
    if title is not None:
        extra += f", title={json.dumps(title, ensure_ascii=False)}"
    if columns is not None:
        extra += f", columns={columns}"
    doc.write_text(text.replace(call, call + extra, 1), encoding="utf-8")
