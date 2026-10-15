# V3.25 Release Notes

V3.25 closes the deployment-activation authority boundary after V3.24 recovery-proof durability.

## Added

- `trading_platform.v325.DeploymentActivationLedger` and `DeploymentActivationRecord`.
- Durable `DEPLOYMENT_ACTIVATION_AUTHORIZED` events in the existing hash-chained `EventStore`.
- Activation validity bounded by both approval and recovery-proof expiry.
- Revalidation against current approval, recovery proof, Operational Truth, state fingerprint and promotion dependency fingerprint.
- Durable conflict detection for reuse of a deployment identity with changed content.
- `AuthorizedDeploymentController` as the production-facing final canary activation wrapper.
- Dedicated V3.25 regression and integration tests.

## Safety position

V3.25 does not create trading authority by itself. It is downstream of promotion, Operational Truth and recovery proof and upstream of the final deployment transition.

A durable activation record cannot increase the canary risk already allocated by the deployment state.

## Verification

- Dedicated V3.25 tests: **10 passed**.
- Full regression: **397 passed**.
- Python compilation: **PASS**.
- Live Binance/Testnet calls: **NOT RUN**.
- Real credentials: **NONE**.
- Exchange mutation: **NONE**.
- `production_ready = FALSE`.
