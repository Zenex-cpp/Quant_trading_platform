# V2.7 Release Notes

V2.7 closes the governance rollback loop with an append-only, hash-chained promotion/demotion audit trail and deterministic Champion rollback.

## Safety properties

- Exactly one active Champion is permitted.
- A rollback target must be non-quarantined, healthy, evidence-valid and approval-valid.
- Rollback requires an explicit actor, reason and timestamp.
- Shadow Challenger state remains risk-zero.
- Audit-chain tampering is fail-closed.
- Governance risk is monotonic with respect to adverse status; rollback cannot invent risk beyond the approved target model's existing budget.
- No exchange network access is required by the V2.7 test suite.

## Production posture

`production_ready = FALSE`. No live or Testnet mutation is performed by the verification suite.
