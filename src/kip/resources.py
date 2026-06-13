"""Read-only resources shipped with every kip installation."""
from pathlib import Path

ASSETS = Path(__file__).resolve().parent / "assets"
TYPST = ASSETS / "typst"
TEMPLATES = ASSETS / "templates"
SKILL = ASSETS / "kip-authoring" / "SKILL.md"
