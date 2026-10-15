import csv
from pathlib import Path
rows=list(csv.DictReader(open(Path(__file__).resolve().parents[1]/"compliance_matrix.csv")))
counts={}
for r in rows: counts[r["implementation_status"]]=counts.get(r["implementation_status"],0)+1
out=Path(__file__).resolve().parents[1]/"docs"/"COMPLIANCE_REPORT.md"
lines=["# Compliance Report V0.1","", "This report distinguishes implementation from verification.", ""]
for k in sorted(counts): lines.append(f"- {k}: {counts[k]}")
lines += ["", "No item is VERIFIED without evidence and review."]
out.write_text("\n".join(lines))
print(out)
