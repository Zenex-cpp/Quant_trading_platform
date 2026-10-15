# V3.28 — Durable Transition Commit Authority

V3.28 closes the crash window left by V3.26/V3.27 between the immutable deployment-state transition and durable execution evidence.

The final activation path is now split into three machine-checkable phases:

1. V3.26 authorization is validated and persisted.
2. V3.28 deterministically plans the exact `DeploymentEvent` without consuming the activation capability.
3. The exact transition is persisted as `DEPLOYMENT_STATE_TRANSITION_EXECUTED` before the caller receives the activated immutable `DeploymentState`.

The persisted execution event contains the source chain head, destination phase, risk transition, event sequence, event hash and transition identity. A retry or process restart can reconstruct the same immutable post-state from the durable event without issuing a second activation authorization.

This is intentionally an append-only execution record; the V3.26 authorization record is not mutated from `AUTHORIZED` into `EXECUTED`.

`production_ready = FALSE` remains mandatory: this release only closes the in-process/crash consistency boundary and does not establish live venue evidence, independent security review, or production approval.
