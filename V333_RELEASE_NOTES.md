# V3.33 Release Notes

V3.33 closes M5 at the final runtime entry boundary and strengthens M30 causal dependency enforcement.

### Added
- `trading_platform/v333/causal_ttl.py`
- `CausalTTLAuthorityLedger`
- durable causal artifact records for Prediction, Signal, Opportunity, Portfolio Decision, Risk Decision and Order Intent
- required dependency-type validation
- downstream TTL containment: a downstream artifact cannot outlive its required upstream artifact
- recursive chain validation with cycle detection
- restart-safe and hash-chain fail-closed behavior

### Enforcement
- `ExecutionRuntimeIntegration` always provisions a causal TTL authority
- OPEN/INCREASE runtime dispatch requires a valid complete causal chain
- intent validity is matched against the durable root artifact window
- missing, expired, invalidated, mismatched or corrupted causal evidence blocks before gateway transport

### Compliance
- M5: `PARTIAL` → `TESTED`
- M30 strengthened through the same recursive dependency validator
- M5/M30 remain `TESTED`, not `VERIFIED`, because independent review and operational evidence are still required

### Verification
- Full suite: **462/462 passed**
- M5/causal focused tests: **16/16 passed**
- `compileall`: PASS
- archive smoke test: PASS
- no Binance/Testnet request
- no real credentials
- `production_ready = FALSE`
