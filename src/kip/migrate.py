"""Convert a project's older TOML inputs into the workbooks kip reads now.

``requirements.toml`` becomes ``input/requirements.xlsx`` and ``sources.toml``
becomes ``input/references.xlsx``. Each converted file is kept beside the new
workbook as ``*.toml.bak`` so nothing is lost, and nothing already in
``input/`` is overwritten.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from .req.model import ITEM_COLUMNS, REQUIREMENT_COLUMNS, VARIABLE_COLUMNS
from .sheets import save_workbook

__all__ = ["REFERENCE_COLUMNS", "requirements_workbook", "references_workbook", "migrate"]

REFERENCE_COLUMNS = ("key", "title", "author", "publisher", "year", "section", "url", "note")


def _sheet(book, title, columns, rows):
    sheet = book.create_sheet(title)
    sheet.append(list(columns))
    for row in rows:
        sheet.append([row.get(c) for c in columns])
    widths = {c: max([len(c)] + [len(str(r.get(c) or "")) for r in rows]) for c in columns}
    for n, column in enumerate(columns):
        sheet.column_dimensions[chr(ord("A") + n)].width = min(60, widths[column] + 2)


def requirements_workbook(data: dict, path: Path) -> Path:
    """Write requirements in the TOML table shape (item/vars/req) as a workbook."""
    from openpyxl import Workbook

    book = Workbook()
    book.remove(book.active)
    item = dict(data.get("item", {}))
    if item.get("parent_file", "").endswith(".toml"):
        item["parent_file"] = str(Path(item["parent_file"]).parent / "input" / "requirements.xlsx")
    _sheet(book, "Item", ITEM_COLUMNS, [item] if item else [])
    _sheet(book, "Variables", VARIABLE_COLUMNS,
           [{"name": name, **raw} for name, raw in data.get("vars", {}).items()])
    _sheet(book, "Inputs", REQUIREMENT_COLUMNS, [
        {"id": rid, **raw, "controls": ", ".join(raw.get("controls", [])) or None}
        for rid, raw in data.get("req", {}).items()])
    return save_workbook(book, path)


def references_workbook(sources: dict, path: Path) -> Path:
    """Write ``{key: {title, author, ...}}`` as a references workbook."""
    from openpyxl import Workbook

    book = Workbook()
    book.remove(book.active)
    _sheet(book, "Inputs", REFERENCE_COLUMNS,
           [{"key": key, **raw} for key, raw in sources.items()])
    return save_workbook(book, path)


def migrate(root: Path) -> list[tuple[Path, Path]]:
    """Convert the TOML inputs in ``root``; return ``(old, new)`` pairs."""
    done = []
    for name, target, convert in (
        ("requirements.toml", "input/requirements.xlsx",
         lambda data, out: requirements_workbook(data, out)),
        ("sources.toml", "input/references.xlsx",
         lambda data, out: references_workbook(data.get("sources", {}), out)),
    ):
        old, new = root / name, root / target
        if not old.exists():
            continue
        if new.exists():
            raise FileExistsError(f"{new} already exists; merge {old.name} into it by hand")
        convert(tomllib.loads(old.read_text(encoding="utf-8")), new)
        old.rename(old.with_name(old.name + ".bak"))
        done.append((old, new))
    return done
