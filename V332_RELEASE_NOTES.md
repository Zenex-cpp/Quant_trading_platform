# V3.32 Release Notes

V3.32 closes the M4 stale-market-data gap at the final runtime entry boundary.

### Added
- `trading_platform/v332/market_authority.py`
- durable `MarketDataAuthorityLedger`
- `MarketDataAuthorityRecord` and `MarketDataAuthorityState`
- timestamp-order validation for `event_time`, `receive_time`, `processing_time`
- explicit `max_age_ms` freshness contract
- restart-safe market-data freshness evidence
- fail-closed behavior for missing, stale, not-yet-valid and corrupted market-data authority

### Enforcement
- `GuardedExecutionDispatcher` can consult the market-data authority for OPEN/INCREASE actions
- `ExecutionRuntimeIntegration` always provisions a market-data authority, so production runtime entry is fail-closed when no fresh market-data evidence exists
- stale market data is rejected before exchange transport
- the runtime simulation clock is reused by the market-data gate, preventing TTL clock skew

### Compliance
- M3 remains `TESTED`
- M4: `PARTIAL` -> `TESTED`
- neither is marked `VERIFIED` because independent review and live evidence remain outstanding

### Verification
- Full suite: **450/450 passed**
- compileall: PASS
- No Binance/Testnet request
- No real credentials
- `production_ready = FALSE`
