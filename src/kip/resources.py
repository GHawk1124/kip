"""Read-only resources shipped with every kip installation."""
from pathlib import Path

ASSETS = Path(__file__).resolve().parent / "assets"
TYPST = ASSETS / "typst"
TEMPLATES = ASSETS / "templates"
SKILL = ASSETS / "kip-authoring" / "SKILL.md"
#: The short working loop every new project carries for whichever agent opens it.
AGENTS = ASSETS / "kip-authoring" / "AGENTS.md"
