# V3.10 Release Notes

V3.10 closes the end-to-end Binance USDⓈ-M user-data lifecycle as a deterministic supervisor over V3.7–V3.9.

Core cycle:

`START control -> socket CONNECT -> ACTIVE -> keepalive scheduler -> keepalive failure/expiry -> controlled reconnect -> RECOVERING -> REST reconciliation proof -> ACTIVE`

Safety contract:
- `tick()` performs at most one control-plane action; production scheduling remains external and deterministic.
- A successful `userDataStream.start` is required before the first socket connection.
- A keepalive failure quarantines the socket and removes trading permission.
- Reconnect always obtains/refreshes a listenKey through the control plane and enters `RECOVERING`.
- Reconnection never restores trading permission by itself; the V3.7 recovery assessment must prove orders, positions and accounting reconciled.
- Recovery failure leaves the runtime `BLOCKED`.
- STOP transport ambiguity is treated as uncertain and quarantines the runtime instead of assuming success.
- Credentials are passed at operation time and are not persisted.
- No real exchange/network call is performed by the test suite.

Current Binance USDⓈ-M documentation verified during V3.10:
- `userDataStream.start`, `userDataStream.ping`, and `userDataStream.stop` are documented on `wss://ws-fapi.binance.com/ws-fapi/v1`.
- `start` returns a `listenKey` and refreshes an already-active key; `ping` returns the current `listenKey`; the stream closes after 60 minutes without keepalive.
