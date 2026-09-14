"""Regenerate only simple_filter, from its editable constants.csv table."""
import subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
for script in ['cad_model.py','views.py','calculate.py','author_document.py']:
    subprocess.run([sys.executable,str(ROOT/script)],cwd=ROOT,check=True)
subprocess.run([str(Path(sys.executable).parent/'kip.exe'),'build','--output','simple_filter.pdf'],cwd=ROOT,check=True)
