# V3.14 — Persistent Order Lifecycle & Restart Recovery

V3.14 extends the V3.13 durable execution correlation layer with a persistent, replayable order lifecycle.

## Delivered
- SQLite-backed `OrderExecutionState` transition journal with monotonic sequence.
- Deterministic replay from `CREATED` through persisted transitions.
- Idempotent transition application using `(intent_id, idempotency_key)`.
- Conflict detection for reused idempotency keys with incompatible event/state.
- Restart-safe lifecycle registry independent of in-memory state.
- Cross-check between durable correlation, lifecycle replay and execution event journal.
- Explicit preservation of `UNKNOWN` as a consistency-valid but trading-blocking state.
- No credentials, sockets, transports or secrets persisted.

## Safety contract
A restart may reconstruct lifecycle state, but reconstruction never grants trading permission. `UNKNOWN` remains blocking until the existing reconciliation path verifies the execution state.

## Verification
- Full suite: 300 passed.
- Targeted V3.10–V3.14 suite: 59 passed.
- Exchange/Testnet calls: none.
- Real credentials: none.
- Exchange mutations: none.
- `production_ready = FALSE`.
