# V3.8 Release Notes

V3.8 adds a network-injected Binance user-data WebSocket runtime boundary on top of V3.7.

Core path:

`listenKey -> WebSocket connect -> heartbeat/keepalive -> user event -> V3.7 journal/correlation -> disconnect -> reconnect -> REST reconciliation -> trading re-enable`

Safety rules:
- Socket reconnect never re-enables trading by itself.
- Keepalive is explicit and credential/network state is not persisted by the runtime.
- WebSocket transport is dependency-injected; tests remain network-free.
- Socket close/disconnect forces trading off through the V3.7 coordinator.
- Recovery remains authoritative before trading resumes.

No live or Testnet exchange calls were executed for verification.
