# V3.80 Verification Report

## Verification summary

- Full suite: **750/750 PASS**.
- V3.80 targeted tests: **13/13 PASS**.
- Limit `OrderIntent -> OrderRequest` mapping: PASS.
- LIMIT parameter encoding (`price`, `timeInForce`): PASS.
- Invalid LIMIT contract rejection: PASS.
- Routed private WebSocket URL construction: PASS.
- `ORDER_TRADE_UPDATE` projection: PASS.
- Duplicate trade deduplication: PASS.
- Out-of-order fail-closed behavior: PASS.
- `ACCOUNT_UPDATE` position projection: PASS.
- REST/WS reconciliation green path: PASS.
- REST/WS mismatch red path: PASS.
- listenKey expiry fail-closed: PASS.
- stale stream fail-closed: PASS.
- unknown event fail-closed: PASS.

## External reference basis

Current Binance documentation/announcements show the USDⓈ-M private WebSocket
route at `/private`, with `ORDER_TRADE_UPDATE` as an authenticated user-data event
and the documented `T`/`E` ordering semantics. Current Binance documentation also
lists LIMIT/GTC/IOC/FOK/GTX order semantics and the `ORDER_TRADE_UPDATE` status/
execution fields used by the projector.

## Non-verified boundary

Live Testnet DNS/TCP/TLS/API connectivity is not part of the passing automated
suite and remains `NOT_VERIFIED` unless the external runtime probe succeeds.

`production_ready = FALSE`.
