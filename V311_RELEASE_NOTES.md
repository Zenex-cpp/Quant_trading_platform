# V3.11 Release Notes

V3.11 converts the V3.10 runtime `trading_allowed` state into an effective final submit guard.

## Execution path

`TradeCapability -> CommitCoordinator -> ExecutionBridge -> GuardedExecutionDispatcher -> Testnet Gateway`

## Hard safety behavior

- No committed request -> no transport call.
- `trading_allowed == False` -> `DispatchGuardDenied`, zero transport calls.
- `recovery_required == True` -> `DispatchGuardDenied`, zero transport calls.
- Local `UNKNOWN` lifecycle -> reconciliation error, zero transport calls.
- Only `SUBMITTED`, `ACKNOWLEDGED`, `PARTIALLY_FILLED` local lifecycle states are dispatchable.
- The exact committed `OrderRequest` is sent; no reconstruction, mutation, or quantity expansion occurs at the final boundary.
- Cancel / close-only is not inferred from the submit guard; it remains a separate authorization path.
- Runtime credentials remain operation-scoped and are not persisted by the dispatcher.

## Verification

- Full suite: **287 passed**
- New V3.11 tests: **4 passed**
- No Binance/Testnet network call executed by the suite.
- No production credentials used.
- No exchange mutation executed.
- `production_ready = FALSE`
