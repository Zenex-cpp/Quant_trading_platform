# V1.5 Binance External References

Reference checked: 2026-09-11.

- Binance Futures WebSocket Testnet base URL is documented as `wss://fstream.binancefuture.com` in the Binance change log.
- USDⓈ-M Futures user-data WebSocket API currently documents `userDataStream.start`, `userDataStream.ping`, and `userDataStream.stop` on `wss://ws-fapi.binance.com/ws-fapi/v1` for the production catalog.
- Current Binance symbol-filter documentation continues to define PRICE_FILTER and LOT_SIZE constraints; adapter-level validation must use current exchangeInfo rather than frozen assumptions.

These references govern adapter implementation only; they do not alter the venue-agnostic core contracts.
