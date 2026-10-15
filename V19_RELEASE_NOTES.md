# V1.9 — User Data State Integrity

V1.9 adds a deterministic, venue-event-normalization layer for the USDⓈ-M User Data Stream contract and an event-driven reconciliation trigger.

Included:
- `ORDER_TRADE_UPDATE`, `ACCOUNT_UPDATE`, `MARGIN_CALL`, `listenKeyExpired` normalization.
- Monotonic event ordering guard; stale/out-of-order and expired-stream states fail closed.
- Keepalive policy with a mandatory margin before the documented 60-minute stream expiry.
- Stream health monitor that blocks trading when state becomes stale/expired.
- Reconciliation triggers on account changes, terminal order updates, margin calls, stream expiry, and unknown events.
- No WebSocket dependency is added: transport remains an explicit boundary and live exchange evidence is not fabricated.

The current Binance USDⓈ-M User Data Stream documentation states that streams expire after 60 minutes without keepalive and exposes `userDataStream.start`, `userDataStream.ping`, and `userDataStream.stop` on `wss://ws-fapi.binance.com/ws-fapi/v1`.
