# V3.54 Release Notes

## Scope
M27 — `Final Holdout improper access invalidates dependent evidence`.

## Enforcement
- Added `HoldoutCompromiseAuthorityLedger` under `trading_platform/v354/holdout_compromise.py`.
- Final Holdout unauthorized access now records a durable `FINAL_HOLDOUT_COMPROMISED` state before dependent invalidation.
- Dependent evidence/gates/candidates/promotions are invalidated through the existing `DependencyInvalidationLedger` and explicit durable `FINAL_HOLDOUT_DEPENDENT_EVIDENCE_INVALIDATED` events.
- A compromised holdout cannot issue new capabilities and cannot open capabilities issued before the compromise.
- Replacement holdouts are versioned and content-hash bound and must be durably registered before a replacement capability can be issued.
- Revalidation after holdout compromise requires new evidence references; invalidated evidence identities cannot be reused.
- `EvidenceSnapshotAuthority` rejects evidence identities historically invalidated by `FINAL_HOLDOUT_IMPROPER_ACCESS`, including after incident revalidation.
- State remains restart-safe through the append-only, hash-chained `EventStore`.

## Required flow
`COMPROMISED → INCIDENT → INVALIDATE DEPENDENT EVIDENCE → NEW HOLDOUT → REVALIDATE`

## Safety
No Binance/Testnet network request was made. No real credentials were used. No live trading was attempted.

`production_ready = FALSE`
