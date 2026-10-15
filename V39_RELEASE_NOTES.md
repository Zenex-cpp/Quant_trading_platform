# V3.9 Release Notes

V3.9 adds the Binance USDⓈ-M user-data control plane on top of V3.8.

Core path:

`runtime credential -> userDataStream.start -> listenKey -> WebSocket session -> userDataStream.ping -> expiry/recovery -> userDataStream.stop`

Safety rules:
- Control-plane credentials are supplied per call and are never persisted.
- START/PING/STOP require an explicit successful Binance response; failures are never inferred as success.
- A keepalive failure forces the durable session to `EXPIRED` and blocks trading.
- `listenKeyExpired` remains a hard recovery event; a new key is required before a new socket session can become active.
- Socket reconnection from V3.8 does not bypass the V3.7 REST reconciliation gate.
- Tests use an injected transport and do not perform exchange calls.

Current Binance USDⓈ-M WS API documentation used for the contract:
- `userDataStream.start` starts/refreshes the active user data stream and returns a `listenKey`.
- `userDataStream.ping` keeps the stream alive and returns the current `listenKey`.
- The stream closes after 60 minutes without keepalive.
- `userDataStream.stop` closes the user data stream.
- The documented control endpoint is `wss://ws-fapi.binance.com/ws-fapi/v1`.
