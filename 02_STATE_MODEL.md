# 02 — Orthogonal State Model

## Axes

- Lifecycle: EXPERIMENTAL, CANDIDATE, APPROVED, RETIRED
- Operational Mode: RESEARCH, BACKTEST, SIMULATION, SHADOW, CANARY, LIVE, CLOSING_ONLY
- Health: HEALTHY, DEGRADED, FAILED, FROZEN
- Approval: PENDING, APPROVED, EXPIRED, REVOKED
- Deployment: NOT_DEPLOYED, STAGED, ACTIVE, ROLLED_BACK, FAILED
- Role: NONE, CHALLENGER, CHAMPION

Axes are independent storage dimensions; compatibility is evaluated by policy, never inferred from a single composite state.

## Required invalid examples
- EXPERIMENTAL × LIVE = INVALID
- RETIRED × LIVE = INVALID
- HEALTH=FAILED × LIVE = INVALID
- APPROVAL=EXPIRED × LIVE = INVALID
- CHAMPION × NOT_DEPLOYED = INVALID

## Action classes
Actions: OPEN, INCREASE, DECREASE, CLOSE, CANCEL, RECONCILE, RETRAIN, DEPLOY, ROLLBACK.
Each action resolves to ALLOW, CONDITIONAL, or BLOCK.

Unknown critical state blocks new risk.
