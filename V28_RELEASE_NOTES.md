# V2.8 Release Notes

V2.8 adds the deployment orchestration boundary between governance and runtime activation.

## Scope

The deployment lifecycle is explicitly staged:

`IDLE → PREPARED → STAGED → CANARY → ACTIVATED`

with terminal safety paths:

`CANARY/STAGED/PREPARED → ABORTED → CLOSED`

`CANARY/ACTIVATED/STAGED → ROLLED_BACK → CLOSED`

## Safety properties

- Promotion bundle, gates, approval, scope, evidence and artifact integrity are required before preparation.
- Mutating deployment is never implicit; canary activation requires the existing rollout limits and approval state.
- Canary risk and exposure are hard-capped by `RolloutPolicy`.
- Activation cannot increase risk beyond the risk already allocated by the canary phase.
- Unhealthy, frozen, blocked or unknown runtime state is fail-closed.
- Abort and rollback force allocated deployment risk to zero.
- Every state transition is appended to an immutable, hash-chained deployment audit chain.
- Audit tampering and sequence gaps are detected before the chain is accepted.
- Terminal states cannot be reopened through this controller.
- No exchange network access is required by the V2.8 verification suite.

## Production posture

`production_ready = FALSE`.
The release contains orchestration primitives and offline verification only; it does not perform live exchange mutations.
