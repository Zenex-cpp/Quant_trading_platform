# V3.50 — M23 Drawdown/Risk-Budget Monotonicity

M23 is implemented as a production drawdown authority. Higher drawdown can only preserve or reduce the risk budget.

Implemented:
- versioned production drawdown method registry;
- conservative monotone drawdown factor;
- LIVE RuntimeAuthority hard cap and provenance fingerprint;
- ExecutionRouter and CapabilityAuthority propagation;
- DurableRiskDecisionLedger validation, persistence and stale-state checks;
- effective-risk integration;
- OFF/ON ablation coverage and focused M23 tests.

Status: TESTED. Independent verification remains required.
