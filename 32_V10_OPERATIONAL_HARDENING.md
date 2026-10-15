# V1.0 — Operational Hardening Checklist

Required before any controlled deployment:

1. Evidence Snapshot is immutable and valid.
2. Promotion Bundle is complete, hashed and scoped.
3. All required gates pass and have not been invalidated.
4. Artifact compatibility is COMPATIBLE, never UNKNOWN.
5. Approval is valid for the exact scope and validity window.
6. Rollback target exists and rollback has been tested.
7. Reconciliation is green; no unresolved critical mismatch.
8. Kill switch is available and tested.
9. Research network cannot reach production trading endpoints.
10. Challenger remains blocked from self-promotion.
11. Shadow produces zero real orders.
12. Canary operates under dedicated absolute bounds.
13. Recovery proof is complete before READY/LIVE.
