# V3.80 Release Notes

## Implemented

- Venue-complete `OrderRequest` fields for LIMIT price and time-in-force.
- Frozen V3.79 adapter preserved; V3.80 introduces a separate LIMIT-capable Testnet gateway boundary.
- Binance USDⓈ-M routed private WebSocket URL builder.
- Deterministic `ORDER_TRADE_UPDATE` projector.
- Deterministic `ACCOUNT_UPDATE` position projector.
- Duplicate trade/event suppression.
- Per-event-type `(T,E)` ordering guard.
- listenKey expiry and stream staleness fail-closed behavior.
- REST/WS account reconciliation gate.

## Verification

- Full automated suite: **750/750 PASS**.
- V3.80-specific tests: **13/13 PASS**.
- No mutating Testnet order was submitted by the release runner.
- Live Testnet connectivity remains `NOT_VERIFIED` when the runtime cannot resolve/reach the external endpoint.

## Explicit limits

- No claim of live network parity.
- No claim of exact exchange matching-engine parity.
- No production execution.
- `production_ready = FALSE`.
