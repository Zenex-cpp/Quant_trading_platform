# V3.81 Verification Report

## Automated verification

- Full regression: **755/755 PASS**.
- V3.81 targeted tests: **5/5 PASS**.
- Deterministic full simulated Testnet chain: PASS.
- Intent -> OrderRequest mapping: PASS.
- Partial fill -> final fill projection: PASS.
- Duplicate trade idempotency / no double count: PASS.
- ACCOUNT_UPDATE -> position projection: PASS.
- REST/WS reconciliation green path: PASS.
- REST/WS reconciliation mismatch red path: PASS.
- FillLedger uniqueness: PASS.
- PositionLedger quantity/average price consistency: PASS.
- Accounting invariants and local/exchange/reconstructed equality: PASS.
- Evidence hash: `f016018cb11c86402e2e312df4376f6f619cd6233e63b46cde52d86538a2e4e2`.

## Live boundary

The read-only Testnet preflight attempted:

`GET https://testnet.binancefuture.com/fapi/v1/time`

Result: **NOT_VERIFIED** because the runtime returned DNS resolution failure. No mutation was executed.

No authenticated account query, private WebSocket session, real order, real fill, or live REST/WS reconciliation has therefore been claimed as verified.

## External reference basis

Binance's March 2026 USDⓈ-M WebSocket migration introduced dedicated Public/Market/Private routes and documents the private production route as `wss://fstream.binance.com/private`, with listenKey + events subscription.

Binance's Futures change log records the Testnet WebSocket base URL as `wss://fstream.binancefuture.com`; combining that Testnet base with the current `/private` routing is treated here as a **reference-derived configuration**, not as live connectivity evidence.

Current user-data documentation describes `ORDER_TRADE_UPDATE`, `ACCOUNT_UPDATE`, same-event ordering by `T`/`E`, and recommends WebSocket user data for order/position state.

## Production boundary

`production_ready = FALSE`.

A real Testnet mutation requires a separate operator-controlled gate, fresh risk/reconciliation state, explicit approval, hard notional ceiling, and a cancellation/recovery plan.
