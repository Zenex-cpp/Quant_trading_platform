# V4.6 Change Impact

## Change
V4.6 adds `GateRevalidationAuthorityV406`.

## Purpose
Turn dependency freshness of an existing gate into a durable, machine-checkable decision. The authority combines:
- explicit gate dependency checkpoint;
- dependency identities from input versions, evidence references and required artifacts;
- active invalidation state from `DependencyInvalidationLedger`;
- post-checkpoint invalidation detection;
- durable, idempotent audit events.

## Safety boundary
The authority performs no network access, process execution, exchange mutation, Testnet mutation, production deployment or secret handling. It can only allow reuse of an already-created gate or fail closed and require a rerun.
