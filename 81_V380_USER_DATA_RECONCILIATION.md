# V3.80 User Data + LIMIT + Reconciliation Contract

## Scope

V3.80 closes the LIMIT-order contract gap left explicitly open in V3.79 and adds a
machine-checkable Binance USDⓈ-M private user-data projection plus REST/WS
reconciliation gate.

## Contract changes

- `OrderRequest` now carries optional `price` and `time_in_force` fields.
- V3.80 has a versioned Testnet gateway subclass so V3.79 remains immutable.
- LIMIT requests require positive price and explicit time-in-force.
- MARKET requests reject price/time-in-force values.
- Current Binance USDⓈ-M private WebSocket routing is represented by the routed
  `/private` base and `/private/ws` access mode.
- `ORDER_TRADE_UPDATE` is projected into deterministic order state.
- `ACCOUNT_UPDATE` is projected into deterministic position state.
- Duplicate raw events and duplicate trade identifiers are suppressed.
- Same-event-type ordering is enforced using `(T, E)`.
- `listenKeyExpired`, stale streams and out-of-order events are fail-closed.
- REST-vs-stream order/position reconciliation is exposed as a trading gate.

## Evidence boundary

The automated evidence proves the local parser, ordering, deduplication, LIMIT
mapping, routed URL construction, and reconciliation behavior. It does not prove
live network connectivity or live exchange matching/latency parity.

`production_ready = FALSE`.
