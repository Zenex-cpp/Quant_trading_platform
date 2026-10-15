# V3.24 Release Notes

V3.24 adds durable recovery-proof authority and binds controlled/live readiness to current-state recovery evidence.

## Added
- `trading_platform.v324.RecoveryProofLedger` and `RecoveryProofRecord`.
- Immutable `RECOVERY_PROOF_RECORDED` evidence in the existing EventStore hash chain.
- Four-predicate recovery verification aligned with the Master Prompt recovery contract.
- Validity-window enforcement for recovery proof.
- Exact current-state fingerprint binding.
- Fail-closed handling for missing, expired, conflicting and corrupted recovery evidence.
- `require_live_readiness(...)` as the machine-checkable M28 integration gate for `CANARY` and `LIVE`.
- Dedicated V3.24 regression tests.

## Deliberate boundary
- `CLOSING_ONLY` does not require recovery proof because it is a containment/reduction mode.
- The recovery-proof artifact never authorizes trading by itself.
- No credentials, sockets, transport state or raw exchange payloads are persisted.

## Verification
- Full regression: **387 passed**.
- Python compilation: **PASS**.
- Live Binance/Testnet calls: **NOT RUN**.
- Real credentials: **NONE**.
- Exchange mutation: **NONE**.
- `production_ready = FALSE`.
