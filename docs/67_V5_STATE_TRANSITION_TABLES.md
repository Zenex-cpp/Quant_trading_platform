# 67 — V5 State Transition Tables

## Scope

The prompt's system lifecycle in §12 and risk system state in §13 are separate machines. They are not the orthogonal `Lifecycle` axis in `docs/02_STATE_MODEL.md`. The prompt names 13 lifecycle states and 6 risk states, but does not specify permitted source/target pairs, guards, or recovery transitions. Until a transition contract is approved, every unlisted pair is rejected. `schemas/v5_state_transition_matrix.csv` enumerates every pair for both machines with that default.

The current base `TransitionEngine` operates on `OrthogonalState`; it is not the runtime for either named prompt machine. Its only registered edge is `START_BACKTEST`: mode `RESEARCH` to `BACKTEST`, with lifecycle, health, approval, deployment, and role unchanged. All other edges are rejected, including otherwise compatible mode changes. The registry and default policy are represented in the same CSV.

## Transition contract

For the registered edge, the engine checks a non-empty idempotency key, validates source and target compatibility, verifies the registered edge, and runs the optional caller guard before recording a commit and audit event. A validation or guard failure leaves the in-memory committed-state and audit ledgers unchanged. An identical replay returns the committed target without rerunning the guard or adding another event; reuse of a key for a different specification is rejected.

The only side effects currently implemented by this engine are updates to its in-memory committed-state map and audit list. It does not provide durable state, external side-effect orchestration, or transactional rollback across external systems. These limits do not meet the production atomicity contract in prompt §10.

## Table interpretation

- `ALLOW` records the one registered base-engine edge and its guards, preconditions, postconditions, side effects, audit event, idempotency behavior, failure state, and recovery path.
- `REJECT_UNDECLARED` means there is no approved positive transition rule for that pair. It is the fail-closed default, not a claim that those states may never be connected by a future reviewed contract.
- The lifecycle and risk pairwise rows are policy inventory only. Neither machine currently has a runtime transition implementation in this base engine.

FD-06 remains `PARTIAL`: the inventory and base-engine allowlist are canonical and tested, while approved positive lifecycle/risk paths and durable atomic side-effect handling remain undefined.
