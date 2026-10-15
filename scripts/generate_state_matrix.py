from itertools import product
import csv
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from trading_platform.state import *

axes = [Lifecycle, OperationalMode, Health, Approval, Deployment, Role]
rows=[]
for values in product(*[list(a) for a in axes]):
    s=OrthogonalState(*values)
    ok, errors=validate_state(s)
    rows.append([x.value for x in values]+["VALID" if ok else "INVALID",";".join(errors)])
path=Path(__file__).resolve().parents[1]/"schemas"/"state_compatibility_matrix.csv"
with path.open("w", newline="") as f:
    w=csv.writer(f); w.writerow(["lifecycle","mode","health","approval","deployment","role","result","reasons"]); w.writerows(rows)
print(f"wrote {len(rows)} states to {path}")
