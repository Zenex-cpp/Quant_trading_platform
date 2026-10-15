# V3.22 Release Notes

## Scope
Durable reconciliation closure for PENDING/UNKNOWN dispatch attempts.

## Changes
- Added `trading_platform.v322.durable_reconciliation.DurableDispatchReconciliationLedger`.
- Added explicit reconciliation evidence binding to the exact V3.21 attempt.
- Added bounded evidence sources: `USER_STREAM`, `REST_ORDER_STATUS`, `SUBMIT_RESPONSE`.
- Added restart-safe recovery closure and unresolved-attempt machine check.
- Preserved no-retry semantics: reconciliation never authorizes resubmission of the original `OrderRequest`.
- Persisted only evidence metadata and fingerprints; no credentials, raw payloads or transport objects.
- Bumped package metadata to `3.22.0`.

## Safety
No live Binance request is executed by the V3.22 verification suite. `production_ready = FALSE` remains unchanged.
