# V3.20 Release Notes

## Scope
Durable committed `AuthorizedOrderRequest` authority and final pre-dispatch binding.

## Changes
- Added `trading_platform.v320.durable_request.DurableOrderRequestLedger`.
- Persisted the full authority decision and full order request through the existing append-only hash-chained `EventStore`.
- Bound each durable request to the exact V3.19 `OrderIntent` fingerprint.
- Added immutable request identity, restart replay, corruption detection and conflicting-reuse rejection.
- Added optional V3.4 bridge persistence of committed requests.
- Added optional V3.11 final dispatch gate requiring the durable request and exact intent-fingerprint binding before risk gates and external transport.

## Safety
- No credentials or exchange transport state are persisted.
- Missing/corrupt/mismatching request authority blocks dispatch.
- No automatic authorization is inferred from persistence alone.
- `production_ready = FALSE`.
