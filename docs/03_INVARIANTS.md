# 03 — Global Invariants Catalog (V0.1)

I-001: no OrderRequest without valid RiskDecision.
I-002: expired RiskDecision is invalid for new risk.
I-003: Position UNKNOWN blocks new orders.
I-004: stale/unknown market data blocks new entry.
I-005: downstream artifacts require all mandatory valid upstream dependencies.
I-006: duplicate retry/replay cannot create duplicate side effects.
I-007: risk reservation cannot be consumed twice.
I-008: non-finite values cannot reach risk/sizing/order boundaries.
I-009: higher uncertainty cannot increase allowed risk.
I-010: worse liquidity cannot increase allowed exposure.
I-011: higher drawdown cannot increase risk budget.
I-012: worse model health cannot increase risk.
I-013: failed compatibility blocks artifact execution.
I-014: failed integrity blocks artifact deployment.
I-015: production activation requires valid approval and promotion evidence.
I-016: recovery is VERIFIED only when state reconciled, invariants pass, no critical issue remains, and guards pass.
I-017: final holdout is unavailable to tuning workflows.
I-018: invalidated dependency requires downstream impact analysis/revalidation.
I-019: immutable historical records are never edited in place.
I-020: no live decision may be based on configuration conflict.
