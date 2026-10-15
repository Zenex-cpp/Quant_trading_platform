# V2.1 Release Notes

- Durable append-only event store with SQLite and `synchronous=FULL`.
- Idempotent append keyed by immutable event ID.
- SHA-256 hash chain with deterministic canonical JSON.
- Event-sourced accounting projection for fills, fees, funding and cash adjustments.
- Deterministic replay with checkpoint/state hash.
- Temporal gap detector with explicit recovery-required state.
- Three-way REST/WebSocket/ledger reconciliation.
- Fail-closed `trading_allowed` semantics.
- Replay CLI for operator verification.

Live execution was not performed in the build environment. No secrets or production credentials are embedded.
