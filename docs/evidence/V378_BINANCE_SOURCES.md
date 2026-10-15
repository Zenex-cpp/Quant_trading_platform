# V3.78 Binance External Reference Record

Reference retrieval: 2026-10-02.

The v3.78 execution model uses current official Binance documentation only for
venue semantics; it does not claim to reproduce undocumented matching-engine
behavior.

References used:

1. Binance USDⓈ-M Futures change log: current `fapi` order/book behavior,
   including `GTX` Post Only, `RPI`, and order-book exclusions for RPI.
   https://developers.binance.com/en/docs/derivatives/usds-margined-futures/change-log
2. Binance error codes: `-5021` FOK order reject and `-5022` GTX/Post Only
   order reject.
   https://developers.binance.com/en/docs/products/derivatives-trading-portfolio-margin/error-code
3. Binance USDⓈ-M Futures market stream subscription documentation,
   including the `btcusdt@depth` stream family.
   https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/websocket-market-streams/Live-Subscribing-Unsubscribing-to-streams
4. Binance futures user-data/order-update documentation: order execution
   statuses include `PARTIALLY_FILLED`, `FILLED`, `CANCELED`, `EXPIRED`; time
   in force includes `GTC`, `IOC`, `FOK`, `GTX`.
   https://developers.binance.com/en/docs/products/derivatives-trading-coin-futures/user-data-streams

Important scope boundary:
- The model uses explicit L2 snapshots and explicit aggressor trade prints.
- Queue position is a deterministic approximation. L2 alone does not expose
  order-level identity or exact queue changes from cancellations/reorders.
- Binance matching-engine internals, hidden liquidity, RPI liquidity, and
  production fee schedules are not silently inferred by this artifact.
