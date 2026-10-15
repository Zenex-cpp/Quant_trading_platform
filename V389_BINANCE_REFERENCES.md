# V3.89 Binance References

The implementation keeps exchange-specific assumptions isolated in the existing Binance adapter.

Official references reviewed on 2026-10-05:

1. Binance derivatives change log: testnet WebSocket base URL history and WebSocket operational requirements.
   https://developers.binance.com/zh-CN/docs/products/derivatives-trading-coin-futures/change-log

2. Binance derivatives WebSocket user-data documentation: authenticated user-data events, ordering and stream-lifecycle guidance.
   https://developers.binance.com/en/docs/products/derivatives-trading-coin-futures/user-data-streams

Exact Testnet REST/WS endpoints must still be revalidated at runtime before any external mutation. V3.89 therefore hard-binds the credential capability to the currently configured Testnet REST host rather than assuming production endpoints are interchangeable.
