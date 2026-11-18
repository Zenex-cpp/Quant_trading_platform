# 67 — V5 State Transition Tables

## Scope

The prompt's system lifecycle in §12 and risk system state in §13 are separate machines. They are not the orthogonal `Lifecycle` axis in `docs/02_STATE_MODEL.md`. The prompt names 13 lifecycle states and 6 risk states, but does not specify permitted source/target pairs, guards, or recovery transitions. Until a transition contract is approved, every unlisted pair is rejected. `schemas/v5_state_transition_matrix.csv` enumerates every pair for both machines with that default.

The current base `TransitionEngine` operates on `OrthogonalState`; it is not the runtime for either named prompt machine. Its only registered edge is `START_BACKTEST`: mode `RESEARCH` to `BACKTEST`, with lifecycle, health, approval, deployment, and role unchanged. All other edges are rejected, including otherwise compatible mode changes. The registry and default policy are represented in the same CSV.

## Transition contract

For the registered edge, `TransitionEngine` checks a non-empty idempotency key, validates source and target compatibility, verifies the registered edge, and runs the optional caller guard before recording an in-memory commit and audit event. A validation or guard failure leaves both in-memory ledgers unchanged. An identical replay returns the committed target without rerunning the guard or adding another event; reuse of a key for a different specification is rejected.

`PersistentTransitionEngine` supports the same registered edge using a file-backed SQLite database. It checks the persisted current state and writes the new state, idempotency record, and audit event inside one `BEGIN IMMEDIATE` transaction. A failed write rolls all three back; after restart, an exact retry returns the saved target without a second audit event. SQLite serializes concurrent writers, and a source-state mismatch or changed idempotency specification is rejected. This implementation rejects caller callback guards because their code and policy are not a durable contract.

The persistent engine performs no external side effect. It guarantees atomicity only for the local state, idempotency, and audit records stored in its SQLite database; it does not claim rollback or exactly-once behavior across a venue, process, or other external system. The engine uses SQLite WAL and full synchronous mode, but does not provide storage replication or tamper-evident audit evidence.

## Table interpretation

- `ALLOW` records the one registered base-engine edge and its guards, preconditions, postconditions, side effects, audit event, idempotency behavior, failure state, and recovery path. The persistent engine applies it only when initialized against a file-backed database.
- `REJECT_UNDECLARED` means there is no approved positive transition rule for that pair. It is the fail-closed default, not a claim that those states may never be connected by a future reviewed contract.
- The lifecycle and risk pairwise rows are policy inventory only. Neither machine currently has a runtime transition implementation in this base engine.

FD-06 remains `PARTIAL`: the registered `START_BACKTEST` edge now has atomic local persistence for state, idempotency, and audit. The prompt does not approve positive paths for its named lifecycle and risk machines, and external side-effect recovery remains unimplemented.
