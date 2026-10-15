# V3.23 Release Notes

V3.23 closes the restart gap in `CommitCoordinator`.

## Added
- `trading_platform.v323.DurableCommitLedger` and `DurableCommitRecord`.
- Durable `ORDER_COMMIT_RECORDED` authority with hash-chain verification through the existing EventStore.
- Restart-safe duplicate behavior for the exact same `OrderIntent`.
- Fail-closed conflict detection for changed commit fingerprints, changed intent fingerprints, and corrupt durable state.
- Explicit handling of durable append races.
- Optional `durable_ledger` integration in `CommitCoordinator`.
- Optional `durable_commit_ledger` wiring in `ExecutionBridge` when the bridge constructs its own CommitCoordinator.
- Seven dedicated V3.23 tests, including restart, crash window and corruption checks.

## Safety position
The durable commit ledger does not authorize trading by itself and does not bypass Operational Truth, risk, accounting, OrderIntent, OrderRequest, dispatch-attempt or reconciliation gates. It prevents the commit layer from recreating a second request after restart.

## Verification
- Full regression: 378 passed.
- Python compilation: PASS.
- No live Binance/Testnet calls.
- No real credentials used.
- `production_ready = FALSE`.
