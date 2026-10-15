# V3.24 — Durable Recovery Proof Authority

V3.24 closes the evidence boundary around recovery proof.

## Problem closed

Earlier releases already implemented pieces of recovery and the logical condition:

`state_reconciled AND invariants_pass AND no_unresolved_critical_issue AND guards_pass`

The remaining weakness was that a caller could represent recovery proof as an in-memory boolean set, without a durable identity, validity window, evidence fingerprints, or a binding to the exact current system state.

## Contract

A production/controlled readiness decision must use a durable `RecoveryProofRecord`.

Required fields:

- proof identity and recovery identity;
- validity window;
- all four recovery predicates;
- state fingerprint;
- reconciliation fingerprint;
- invariants fingerprint;
- guards fingerprint;
- issuance timestamp.

A proof is valid only when:

1. the durable EventStore chain verifies;
2. the proof exists and is structurally valid;
3. all four recovery predicates are true;
4. the current time is inside the proof validity window;
5. the current state fingerprint exactly matches the proof.

## Readiness boundary

`require_live_readiness(...)` is the V3.24 machine-checkable M28 integration point.

`CANARY` and `LIVE` require a valid durable recovery proof in addition to the existing operational-readiness checks.

`CLOSING_ONLY` is intentionally not included in this gate because it is a risk-reduction mode and must remain available for containment/reduction actions.

## Immutability / restart behavior

Proofs are append-only `RECOVERY_PROOF_RECORDED` events in the existing hash-chained EventStore.

Reopening the store restores the same proof identity and content. Reuse with a conflicting payload, corrupted chain, expired validity window, or changed current-state fingerprint fails closed.

## Safety position

V3.24 does not assert production readiness and does not perform exchange I/O. The artifact is an evidence gate, not a trading authorization mechanism. It does not bypass risk, accounting, permissions, deployment, dispatch or reconciliation controls.
