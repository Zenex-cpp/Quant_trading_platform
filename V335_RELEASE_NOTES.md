# V3.35 Release Notes

## Scope
M8 — Final Holdout access is technically blocked from the tuning workflow.

## Implemented
- Capability-gated `HoldoutVault` with private raw rows.
- `FinalHoldoutCapability` issued only for FINAL_EVALUATION/AUDIT.
- Capability issuance is durably recorded and provenance-checked before handle creation.
- Single-use capability consumption is durable and restart-safe.
- Expired, wrong-actor, wrong-workflow, forged, and replayed capabilities fail closed.
- `TuningDataView` exposes TRAIN / VALIDATION / OOS only; FINAL_HOLDOUT is not exposed.
- `TuningSession` cannot evaluate FINAL_HOLDOUT and routes tuning evaluation through the non-holdout surface.
- Packaging metadata aligned to project name `trading-platform` and version `3.35.0`.

## Non-goals
No live trading, no Binance/Testnet requests, no production credentials.

## Compliance
M8 = TESTED, not VERIFIED. Independent review remains required by the Master Prompt.
