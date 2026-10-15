# V1.2 — Testnet Verification & End-to-End Evidence

## Scope
This milestone adds the testnet verification contract and an offline evidence harness. It does **not** claim execution against a live Binance testnet account because no testnet credentials/account/session evidence is available in the repository.

## Mandatory scenarios
TN-01 through TN-10 require live testnet evidence. TN-11 is executable offline and verifies failure/recovery policy semantics.

## Binance references
The current Binance USDⓈ-M Futures documentation describes user-data stream operations over `wss://ws-fapi.binance.com/ws-fapi/v1`, including start/keepalive/stop; user-data streams close after 60 minutes unless kept alive. The documentation also exposes `ORDER_TRADE_UPDATE` and `ACCOUNT_UPDATE` event schemas. These references are external and versioned by retrieval date in the compliance matrix.

The current market-stream documentation states that a websocket connection is valid for 24 hours, sends ping frames every 3 minutes, requires pong response within 10 minutes, allows at most 10 incoming messages per second, and recommends WebSocket user-data messages for order/position state under volatile conditions.

## Evidence rule
A scenario is `VERIFIED` only when:
- raw exchange response/event evidence is captured;
- the exact environment and endpoint are recorded;
- request/response correlation is preserved;
- hashes are recorded;
- pre/post snapshots are stored;
- reconciliation closes without unresolved critical issues;
- required invariants pass;
- reviewer/owner and timestamps are recorded.

Offline contract passes are not substitutes for live testnet evidence.
