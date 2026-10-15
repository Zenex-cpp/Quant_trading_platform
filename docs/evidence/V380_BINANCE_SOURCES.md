# V3.80 Binance Source References

- Binance USDⓈ-M Futures WebSocket System Upgrade Notice (2026-03-06):
  https://www.binance.com/en-NG/support/announcement/detail/ebf9b0aa9eca4ff3804eef6fb09ba32a
  - Private user-data route: `wss://fstream.binance.com/private`
  - Private `/private/ws` listenKey-based routing.
- Binance Developer Docs — USDⓈ-M user-data stream / order update semantics:
  https://developers.binance.com/en/docs/products/derivatives-trading-coin-futures/user-data-streams
  - `ORDER_TRADE_UPDATE`
  - order status / execution type / time-in-force fields
  - same-event-type ordering guidance via `T` / `E`.
- Binance Developer Docs — USDⓈ-M WebSocket API user-data control:
  https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/ws-api/user-data-streams
  - `userDataStream.start`, `.ping`, `.stop`.
- Binance API changelog:
  https://developers.binance.com/zh-CN/docs/products/derivatives-trading-coin-futures/change-log
  - 2026 WebSocket routed-path migration and current USDⓈ-M user-data changes.
