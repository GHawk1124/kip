# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""One command from any directory: uv run /path/to/simple_filter/generate.py."""
import shutil
import subprocess
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
uv = shutil.which("uv")
env = os.environ.copy()
env.pop("VIRTUAL_ENV", None)
if not uv:
    raise SystemExit("Install uv, then run: uv run simple_filter/generate.py")
for script in ["cad_model.py", "views.py", "calculate.py", "author_document.py"]:
    subprocess.run([uv, "run", "--project", str(ROOT), "python", str(ROOT/script)], cwd=ROOT, check=True, env=env)
subprocess.run([uv, "run", "--project", str(ROOT), "kip", "check"], cwd=ROOT, check=True, env=env)
subprocess.run([uv, "run", "--project", str(ROOT), "kip", "build", "--output", "simple_filter.pdf"], cwd=ROOT, check=True, env=env)
print(ROOT / "output/simple_filter.pdf")
