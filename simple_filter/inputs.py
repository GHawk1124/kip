"""One editable constants table drives new CAD and calculations; SI conversions are exact."""
import csv
from pathlib import Path
ROOT=Path(__file__).resolve().parent
ROWS=list(csv.DictReader((ROOT/'constants.csv').open(encoding='utf-8')))
C={r['key']:float(r['value']) for r in ROWS}
assert len(C)==len(ROWS), 'Duplicate constant key'
LB_KG=0.45359237
PSI_PA=6894.757293168
