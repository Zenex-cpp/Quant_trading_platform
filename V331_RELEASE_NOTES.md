# V3.31 Release Notes

V3.31 closes the M3 position-state authority gap.

### Added
- `trading_platform/v331/position_authority.py`
- durable `PositionAuthorityLedger`
- `PositionAuthorityRecord` and `PositionAuthorityState`
- restart-safe position authorization and fail-closed validation

### Enforcement
- `GuardedExecutionDispatcher` consults position authority before transport when configured
- `ExecutionRuntimeIntegration` always provisions the position authority boundary
- missing authority, unknown state, reconciliation mismatch, expired authorization and corrupted EventStore chain block dispatch
- dispatcher clock is aligned with the runtime simulation clock

### Compliance
- M3: `PARTIAL` → `TESTED`
- M3 remains below `VERIFIED` pending independent review and live venue evidence

### Verification
- Full suite: 440 passed
- No live exchange/Testnet request
- No real credentials
- `production_ready = FALSE`
