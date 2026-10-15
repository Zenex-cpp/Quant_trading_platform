# V3.21 Release Notes

## Scope
Durable pre-transport execution-attempt authority and crash-safe no-retry semantics for the exact committed OrderRequest.

## Changes
- Added `trading_platform.v321.durable_dispatch.DurableDispatchAttemptLedger`.
- Persisted `PENDING` before external transport and terminal/UNKNOWN observation after transport.
- Bound each attempt to the exact V3.19 OrderIntent fingerprint and V3.20 OrderRequest fingerprint.
- Added final-dispatch blocking for previous PENDING, UNKNOWN and already-resolved attempts.
- Persisted exception-to-UNKNOWN evidence so a transport ambiguity remains non-retryable.
- Preserved the existing fail-closed and opt-in architecture.
- Corrected package metadata version to `3.21.0`.

## Safety
No credentials, transport/socket state or autonomous network behavior is introduced by the ledger. The verification suite performs no exchange I/O and keeps `production_ready = FALSE`.
