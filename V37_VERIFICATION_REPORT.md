# V3.7 Verification Report

Date: 2026-09-13

## Result

- Full suite: **262 passed**
- V3.6 baseline preserved: **255 passed** before V3.7 additions
- V3.7 tests: **7 passed**
- Live exchange calls: **NOT RUN**
- Credentials used: **NONE**
- Production readiness: **FALSE**

## Critical invariants exercised

1. Durable dedupe survives process restart through SQLite persistence.
2. Disconnect forces `RECONNECTING` and disables trading.
3. Reconnect forces `RECOVERING` and disables trading until proof is supplied.
4. Failed recovery forces `BLOCKED`.
5. `listenKeyExpired` forces `EXPIRED` and requires a fresh active stream.
6. Out-of-order same-event-type observations force recovery without being applied as trusted operational state.
7. A stale active stream disables trading.
8. Recovery callback receives the concrete failure/recovery cause.

## Evidence boundary

No production or Testnet exchange endpoint was called during this verification. All network interaction remains behind explicit adapter/gateway boundaries from prior releases.

## Binance implementation contract

Current Binance USDⓈ-M WebSocket user-data documentation states that user data streams close after 60 minutes unless kept alive and documents `userDataStream.start` and `userDataStream.ping` on `wss://ws-fapi.binance.com/ws-fapi/v1`. It also requires an API key for these user-data-stream operations. The project records these as adapter facts only.

Because the current reference used here does not expose a documented sequence number for the user-data event flow, V3.7 treats same-event-type `T/E` ordering as the local ordering contract and treats every reconnect/stream expiry as an evidence gap requiring REST reconciliation before trading is re-enabled.
