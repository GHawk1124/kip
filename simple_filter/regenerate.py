"""Compatibility entry point; prefer: uv run generate.py."""
import runpy
from pathlib import Path
runpy.run_path(str(Path(__file__).with_name("generate.py")), run_name="__main__")
