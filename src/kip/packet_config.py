"""Editable component conventions. Omitted settings inherit the defaults."""
from dataclasses import dataclass, fields, replace
from pathlib import Path
import re
import tomllib


STAGES = ("overview", "requirements", "inputs", "preliminary", "sizing", "design",
          "analysis", "manufacturing", "test", "compliance")
DEFAULT_STAGE = {"text": "overview", "given": "inputs", "controlled": "inputs",
                 "calc": "analysis", "calculation": "analysis", "symbolic": "sizing",
                 "draw": "design", "plot": "analysis", "table": "analysis",
                 "requirements": "requirements", "sources": "requirements", "verify": "compliance"}


@dataclass(frozen=True)
class Section:
    title: str
    columns: int | str = "default"
    required: bool = True
    generate: bool = True


@dataclass(frozen=True)
class SheetSpec:
    path: str
    sheet: str
    columns: tuple[str, ...]
    required: tuple[str, ...]
    stage: str
    optional: bool = False
    enabled: bool = True


SHEETS = {
    "constants": SheetSpec("input/constants.xlsx", "Inputs",
        ("key", "value", "unit", "description", "basis", "symbol", "source"), ("key", "value"), "inputs"),
    "documents": SheetSpec("input/references.xlsx", "Documents",
        ("description", "organization", "number"), ("description", "organization", "number"), "requirements", True),
    "references": SheetSpec("input/references.xlsx", "Inputs",
        ("key", "title", "author", "publisher", "year", "section", "url", "note"), ("key", "title"), "requirements", True),
    "process": SheetSpec("input/process.xlsx", "Inputs",
        ("id", "operation", "acceptance"), ("id", "operation", "acceptance"), "manufacturing"),
    "tests": SheetSpec("input/tests.xlsx", "Inputs",
        ("id", "requirement", "procedure", "criterion", "result", "evidence"),
        ("id", "requirement", "procedure", "criterion"), "test"),
}
REQUIREMENTS_SHEET = SheetSpec("input/requirements.xlsx", "Inputs",
                             ("id", "text", "verification"), ("id", "text", "verification"), "requirements")


def _keys(raw, allowed, where):
    if not isinstance(raw, dict):
        raise ValueError(f"{where}: expected a table")
    unknown = set(raw) - set(allowed)
    if unknown:
        raise ValueError(f"{where}: unknown setting(s): {', '.join(sorted(unknown))}")


def _strings(value, where):
    if not isinstance(value, (list, tuple)) or any(not isinstance(s, str) or not s.strip() for s in value):
        raise ValueError(f"{where}: expected a list of nonempty strings")
    if len(value) != len(set(value)):
        raise ValueError(f"{where}: duplicate entries")
    return tuple(value)


def _identifier(value):
    return isinstance(value, str) and re.fullmatch(r"[a-z][a-z0-9_]*", value)


class PacketConfig:
    def __init__(self, path: Path):
        raw = tomllib.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        _keys(raw, ("order", "sections", "defaults", "na", "sheets", "requirements_file"), "packet")
        self.order = _strings(raw.get("order", STAGES), "order")
        if not self.order or any(not _identifier(s) for s in self.order):
            raise ValueError("order: use at least one section id (lowercase letters, digits, underscores)")
        self.sections = {s: Section("Preliminary Analysis" if s == "preliminary" else s.replace("_", " ").title())
                         for s in self.order}
        sections = raw.get("sections", {})
        _keys(sections, self.order, "sections (add custom sections to order)")
        for name, settings in sections.items():
            _keys(settings, (f.name for f in fields(Section)), f"sections.{name}")
            section = replace(self.sections[name], **settings)
            if not isinstance(section.title, str) or not section.title.strip():
                raise ValueError(f"sections.{name}.title: expected nonempty text")
            if section.columns != "default" and (type(section.columns) is not int or section.columns not in (1, 2)):
                raise ValueError(f"sections.{name}.columns: use 1, 2, or 'default'")
            if type(section.required) is not bool or type(section.generate) is not bool:
                raise ValueError(f"sections.{name}: required and generate must be booleans")
            self.sections[name] = section
        self.na = set(_strings(raw.get("na", ()), "na"))
        if self.na - set(self.order):
            raise ValueError("na: sections must appear in order")
        defaults = raw.get("defaults", {})
        _keys(defaults, DEFAULT_STAGE, "defaults")
        if any(stage not in self.order for stage in defaults.values()):
            raise ValueError("defaults: target sections must appear in order")
        self.defaults = DEFAULT_STAGE | defaults
        self.requirements_file = raw.get("requirements_file", "requirements.toml")
        if not isinstance(self.requirements_file, str) or not self.requirements_file.strip():
            raise ValueError("requirements_file: expected a TOML path")
        sheets = raw.get("sheets", {})
        if not isinstance(sheets, dict):
            raise ValueError("sheets: expected a table")
        specs = {"requirements": REQUIREMENTS_SHEET, **SHEETS}
        for name, settings in sheets.items():
            if not _identifier(name):
                raise ValueError(f"sheets: invalid sheet id {name!r}")
            _keys(settings, (f.name for f in fields(SheetSpec)), f"sheets.{name}")
            if name in specs:
                specs[name] = replace(specs[name], **settings)
            else:
                missing = {"path", "columns", "stage"} - set(settings)
                if missing:
                    raise ValueError(f"sheets.{name}: supply {', '.join(sorted(missing))}")
                specs[name] = SheetSpec(**({"sheet": "Inputs", "required": ()} | settings))
        self.sheets = {}
        for name, spec in specs.items():
            for key in ("path", "sheet", "stage"):
                if not isinstance(getattr(spec, key), str) or not getattr(spec, key).strip():
                    raise ValueError(f"sheets.{name}.{key}: expected nonempty text")
            if spec.stage not in (*STAGES, *self.order):
                raise ValueError(f"sheets.{name}: unknown stage {spec.stage!r}")
            if type(spec.enabled) is not bool or type(spec.optional) is not bool:
                raise ValueError(f"sheets.{name}: enabled and optional must be booleans")
            columns = _strings(spec.columns, f"sheets.{name}.columns")
            required = _strings(spec.required, f"sheets.{name}.required")
            if not columns or set(required) - set(columns):
                raise ValueError(f"sheets.{name}: required fields must be listed in columns")
            semantic = {"constants": {"key", "value"}, "requirements": {"id", "text", "verification"},
                        "references": {"key", "title"}, "tests": {"requirement", "result", "evidence"}}
            if spec.enabled and semantic.get(name, set()) - set(columns):
                raise ValueError(f"sheets.{name}: missing columns needed by its built-in reader")
            if spec.enabled and spec.stage in self.order:
                self.sheets[name] = replace(spec, columns=columns, required=required)
