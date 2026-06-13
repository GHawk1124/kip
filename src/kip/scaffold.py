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
                   template: str = "basic", source: str | None = None) -> list[Path]:
    """Populate an empty directory. Never overwrite an existing project."""
    from .render.layout import Layout, PageSpec

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
        if file.is_file():
            shutil.copyfile(file, root / file.name)
    pyproject = tomlkit.document()
    pyproject["project"] = {"name": slug, "version": "0.1.0",
                            "description": doc_title, "requires-python": ">=3.12",
                            "dependencies": [requirement]}
    pyproject["tool"] = {"uv": {"package": False}}
    (root / "pyproject.toml").write_text(tomlkit.dumps(pyproject), encoding="utf-8")
    (root / ".python-version").write_text("3.12\n", encoding="utf-8")
    (root / ".gitignore").write_text(".venv/\n__pycache__/\noutput/\n", encoding="utf-8")
    lp = root / "layout.toml"
    layout = Layout.load(lp) if lp.exists() else Layout(page=PageSpec())
    layout.page.title = doc_title
    layout.save(lp)
    skill = root / ".agents" / "skills" / "kip-authoring" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_bytes(SKILL.read_bytes())
    return sorted(p for p in root.rglob("*") if p.is_file())
