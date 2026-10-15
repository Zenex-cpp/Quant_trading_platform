# V3.19 Release Notes

## Scope
Durable OrderIntent authority and final dispatch binding.

## Changes
- Added `trading_platform.v319.durable_intent.DurableOrderIntentLedger`.
- Persisted complete `OrderIntent` identity through the existing append-only hash-chained EventStore.
- Added deterministic fingerprinting and immutable `intent_id` semantics.
- Added restart replay and corruption detection.
- Added optional V3.19 final dispatch gate requiring durable intent existence and payload match.
- Preserved fail-closed behavior and all prior V3.16–V3.18 gates.

## Safety
- No credentials or exchange transport state are persisted.
- Missing/corrupt/mismatching intent blocks before transport.
- No automatic authorization is inferred from persistence alone.
- `production_ready = FALSE`.
