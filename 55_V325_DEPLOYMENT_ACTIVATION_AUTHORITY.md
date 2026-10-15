# V3.25 — Durable Deployment Activation Authority

## Purpose

V3.25 closes the authority gap between operational readiness and controlled deployment activation.

A `CANARY`/`LIVE` activation is no longer represented by a non-durable readiness boolean alone. The production-facing activation boundary requires a durable activation authorization bound to the current:

- recovery proof;
- operational state fingerprint;
- Operational Truth hash;
- promotion dependency fingerprint;
- approval;
- requested/effective risk;
- deployment identity.

## Machine contract

`DeploymentActivationLedger.authorize(...)` fails closed unless:

1. the activation target is `CANARY` or `LIVE`;
2. the full `OperationalReadiness` contract is ready;
3. a valid, current V3.24 recovery proof exists;
4. the Promotion Bundle and promotion gates are valid;
5. the Runtime Authority authorizes `DEPLOY`;
6. rollout policy accepts the requested risk and exposure;
7. runtime mode matches the activation target;
8. `LIVE` has `CHAMPION` role;
9. the derived activation validity window is non-empty.

The resulting `DEPLOYMENT_ACTIVATION_AUTHORIZED` event is append-only and hash-chained through the existing `EventStore`.

## Revalidation contract

`assert_valid(...)` revalidates the activation before final use. Any mismatch in:

- approval validity/status;
- current state fingerprint;
- current Operational Truth hash;
- current promotion dependency fingerprint;
- recovery-proof fingerprint;
- activation TTL;

invalidates the authorization and requires a new authorization decision.

## Risk monotonicity

The authorization records both requested and effective risk. The V3.25 controller rejects final canary activation if the deployment state would exceed the durable authorization's effective risk. No activation path in V3.25 can use the artifact to increase the already-allocated risk.

## Deployment boundary

`AuthorizedDeploymentController` is the production-facing wrapper around the legacy V3.28 deployment primitive. It requires durable V3.25 authorization before calling the final canary activation transition.

The legacy V3.28 orchestrator remains available as a lower-level primitive for compatibility and tests; V3.25 does not treat direct use of that primitive as production authorization.

## Evidence boundary

The implementation establishes automated test evidence only. It does not establish live/testnet exchange evidence, infrastructure isolation, independent security review, human approval, disaster-recovery exercise evidence, or production readiness.
