# V3.56 Release Notes

Requirement: M29 — Risk budget cannot increase solely because state worsened.

V3.56 adds a durable risk-state monotonicity authority. The six risk states are explicitly ordered for risk tightening and have a conservative production factor registry. A worse state cannot increase remaining budget, available new risk, or maximum exposure unless a specific recovery event is validated, audited, bound to a current RecoveryProof, within its validity window, and within its explicit ceilings.

The runtime authority now applies the state cap from `OperationalTruth.risk_state`. Durable risk decisions persist the state factor and reject allowed exposure above the state-derived cap unless a recovery-event binding is present. Legacy NORMAL behavior retains the historical authority fingerprint/reason codes.
