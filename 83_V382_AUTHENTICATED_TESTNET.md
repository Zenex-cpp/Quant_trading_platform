# V3.82 — Authenticated Testnet Session

## Scope

V3.82 creates the controlled authenticated boundary for Binance USDⓈ-M Testnet user-data. It does not submit orders.

Path:

`USER_STREAM_CONTROL → PRIVATE_WS → USER_DATA_PROJECTION → RECONCILIATION_GATE`

The control plane uses `userDataStream.start`, `userDataStream.ping`, and `userDataStream.stop`. The user-data stream is kept separate from order submission.

## Safety

`TESTNET` is mandatory. Production hosts are rejected by `TESTNET_POLICY`.

API keys are accepted at runtime and not persisted by the session object. The authenticated session never writes the API secret to evidence or transport payloads.

A failed control request, failed reconnect, malformed WebSocket payload, out-of-order event, stale stream, or `listenKeyExpired` event blocks trading.

## Verification boundary

Local fake-transport tests verify the state machine, credential handling, keepalive, listen-key rotation, expiry and fail-closed behavior.

Actual authenticated Testnet connectivity is external evidence and remains `NOT_VERIFIED` when the runtime has no network access or credentials.
