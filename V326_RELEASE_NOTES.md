# V3.26 Release Notes

V3.26 closes the final public-API bypass between durable V3.25 deployment authorization and the legacy V3.28 activation primitive.

## Added

- Protected activation capability/context in `trading_platform.v28.deployment_authority`.
- Direct `DeploymentOrchestrator.activate()` blocking without activation authority.
- Durable `StateTransitionAuthorityLedger` in `trading_platform.v326`.
- `DeploymentStateTransitionAuthority` as the machine-enforced final `CANARY -> ACTIVATED` boundary.
- Transition identity conflict detection and hash-chain integrity checks.
- Postcondition checks for target phase and authorized risk ceiling.
- Dedicated V3.26 tests.

## Changed

- The V3.25 `AuthorizedDeploymentController` now installs a validated activation capability before invoking V3.28 final activation.
- V3.28 unit tests explicitly exercise the protected capability path instead of treating direct activation as valid.

## Verification

- Full regression: **403 passed**.
- Python compilation: **PASS**.
- No live Binance/Testnet calls.
- No real credentials.
- No exchange mutation.
- `production_ready = FALSE`.

## Boundary

V3.26 makes the final in-process deployment transition machine-guarded and durable-authorized. It does not claim distributed atomic commit with deployment infrastructure or external systems.
