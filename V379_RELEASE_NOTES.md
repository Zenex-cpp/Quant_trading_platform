# V3.79 Release Notes

## Scope

V3.79 extends §85/§86 from decision-stage parity to the execution seam and
introduces a controlled Binance USDⓈ-M Testnet adapter boundary.

## Implemented

- Non-vacuous backtest/live-shadow execution-seam parity.
- Deterministic intent fingerprint comparison.
- Execution adapter observation normalization and hashing.
- Testnet mutation gate: disabled by default, explicit operator approval, hard
  notional ceiling.
- MARKET `OrderIntent -> OrderRequest` deterministic adapter mapping.
- Read-only Testnet public probe for server time and exchange information.
- LIMIT submission intentionally blocked until `OrderRequest` carries price and
  time-in-force semantics.

## Verification

- 737/737 automated tests PASS.
- No network-mutating order was submitted by the release runner.
- Public Testnet connectivity evidence is `NOT_VERIFIED` because external DNS was
  unavailable in the execution runtime.

## Explicit limits

- No production execution.
- No claim of live latency/matching parity.
- User-data WebSocket parity remains open.
- `production_ready = FALSE`.
