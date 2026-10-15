# V3.16 Release Notes

V3.16 closes the accounting-to-execution safety gap identified after V3.15.

Added:
- `trading_platform/v316/accounting_gate.py`;
- explicit machine-checkable accounting states `UNRECONCILED`, `RECONCILED`, `ADJUSTED`, `UNKNOWN`;
- durable accounting authority with restart reconstruction;
- fail-closed risk gate: new risk is allowed only after explicit reconciliation/adjustment evidence;
- integration of the accounting gate into the V3.11 final submit boundary;
- regression coverage proving zero transport calls when accounting is unresolved.

Safety posture:
- accounting reconstruction alone never grants trading permission;
- every new accounting event reverts the gate to `UNRECONCILED` until revalidated;
- `UNKNOWN` blocks new risk;
- no credentials or network I/O added;
- `production_ready = FALSE` remains unchanged.
