# V3.38 — M11 durable side-effect retry/replay boundary

M11 is strengthened at the real external side-effect boundary.

- `DurableSideEffectLedger` persists `STARTED`, `SUCCEEDED`, and `UNKNOWN` states in the existing hash-chained EventStore.
- The `STARTED` marker is durable before external transport is entered.
- A retry/restart seeing `STARTED` or `UNKNOWN` is fail-closed and cannot call the external gateway again.
- A completed side effect stores only a normalized non-secret result and a retry replays that result without re-executing the side effect.
- Operation identity binds operation type, idempotency key, and payload fingerprint.
- Tampered or structurally invalid side-effect journals fail closed.
- `GuardedExecutionDispatcher` now uses the durable side-effect executor around the external order-submit call.
- The replay result is intentionally limited to normalized observation fields; raw gateway payloads and credentials are never persisted.
- Existing durable dispatch-attempt protection remains in place as the lower-level pre-transport crash guard.

External exchange infrastructure cannot provide a mathematical exactly-once guarantee from this code alone; unresolved exchange state still requires reconciliation.
