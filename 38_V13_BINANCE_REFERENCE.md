# V1.3 Binance Reference Record

Reference retrieval: 2026-09-11.

The current official Binance USDⓈ-M Futures WebSocket API documents user-data stream operations such as `userDataStream.start`, `userDataStream.ping`, and `userDataStream.stop`, with a 60-minute user-data stream lifetime absent keepalive. The current USDⓈ-M Futures change-log also documents the `/fapi/v1/*` REST family and newer `/fapi/v3/*` account endpoints. These references are treated as external references and must be versioned in implementation configuration.

The current market-stream documentation states that a single WebSocket connection is valid for 24 hours, server ping frames are sent every 3 minutes, pong must be received within 10 minutes, and a connection accepts at most 10 incoming messages per second. The same documentation recommends WebSocket user-data state for order/position information under volatile conditions.

Source URLs:
- https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/ws-api/user-data-streams
- https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/websocket-market-streams/Connect
- https://developers.binance.com/en/docs/products/derivatives-trading-usds-m-futures/change-log
