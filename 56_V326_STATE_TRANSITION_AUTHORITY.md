# V3.26 — Machine-Enforced Deployment State-Transition Authority

## Purpose

V3.26 closes the remaining public-API bypass between V3.25 durable deployment activation authority and the legacy V3.28 final activation primitive.

The final `CANARY -> ACTIVATED` transition is now a protected state-transition operation:

`V3.25 activation authorization -> V3.26 transition authorization -> capability context -> V3.28 transition primitive`

## Machine contract

`DeploymentStateTransitionAuthority.activate(...)` fails closed unless:

1. the source deployment phase is `CANARY`;
2. the V3.25 activation record exists and is currently valid;
3. the activation record still matches state, Operational Truth, promotion dependencies and approval;
4. bundle, approval and requested risk still match the deployment state;
5. the already allocated risk does not exceed the durable activation effective risk;
6. a durable V3.26 transition authorization can be recorded/reused without identity conflict;
7. the V3.28 primitive receives the matching protected activation capability;
8. the resulting phase is exactly `ACTIVATED`; and
9. the resulting allocated risk does not exceed the authorized effective risk.

## Legacy primitive protection

`DeploymentOrchestrator.activate()` is no longer a public unguarded final-transition path. It requires a capability installed through the V3.28 authority context and rejects direct invocation with:

`DEPLOYMENT_ACTIVATION_AUTHORITY_REQUIRED`

The existing prepare/stage/canary/rollback/close primitives remain available. The final transition is the protected boundary.

## Durable transition authority

V3.26 adds `StateTransitionAuthorityLedger`, backed by the existing hash-chained `EventStore`.

The authorization record binds:

- transition identity;
- deployment identity;
- source/target phase;
- V3.25 activation fingerprint;
- current state fingerprint;
- current Operational Truth hash;
- requested/effective risk;
- operator and decision IDs;
- authorization timestamp.

Reuse of the same transition identity with changed content is rejected. Corruption of the durable EventStore chain blocks authorization reuse.

## Atomicity boundary

The durable V3.26 record is an authorization artifact written before the legacy state transition is invoked. The implementation does not claim a distributed two-phase commit across independent durable deployment state and external infrastructure; such evidence remains outside this milestone.

## Evidence boundary

Automated evidence covers the state-transition authority, direct legacy activation blocking, durability, conflict detection, state/truth invalidation, risk monotonicity and corruption fail-closed behavior.

It does not establish live exchange evidence, infrastructure isolation, independent security review, human approval evidence, disaster-recovery exercise evidence, or production readiness.
