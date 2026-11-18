# V5.0 Risk State Model

This is the canonical machine-readable model for the six risk states required by
MASTER PROMPT §13 and §179 FD-21. The state is independent from lifecycle,
operational mode, health, approval, deployment, and role axes.

## Invariants

- Unknown state or unknown catalog row fails closed.
- Severity is ordered from `NORMAL` to `RECOVERY`.
- The risk factor never increases as severity worsens.
- A factor of zero blocks new risk. Existing positions may only be reduced,
  closed, cancelled, or reconciled according to the row policy.
- `RECOVERY` requires a verified recovery proof and reconciliation before
  readiness or live activation.

`schemas/v5_risk_state_model.csv` is the source of truth. The loader checks the
rows against `RiskSystemState`, and the existing M29 authority enforces the same
conservative factors at durable risk decisions. Its helper applies the factor to
a caller-supplied baseline ceiling and rejects requests above the resulting cap.
This artifact defines local behavior only; it does not prove that a
production-wide risk state is connected.
