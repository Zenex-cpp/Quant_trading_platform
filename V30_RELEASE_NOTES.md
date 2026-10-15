# V3.0 Release Notes

V3.0 introduces the Operational Truth Model, a canonical immutable state that combines lifecycle/operational mode/health/approval/deployment/role axes with health, provenance, governance, accounting, ledger, reconciliation and risk constraints.

Hard rules:
- blocked or unknown truth => zero effective risk;
- stale decisions => zero effective risk;
- effective risk is the minimum across all hard caps;
- deployment requires verified health/provenance/governance/reconciliation/accounting/ledger;
- reconciliation remains an allowed recovery action under non-blocked uncertainty;
- all canonical state is hashable and deterministic.

No live exchange mutation is performed by the V3.0 test suite.
