# V3.79 Binance External References

Reference retrieval: 2026-10-03.

1. Binance Developer Documentation — General API information and SIGNED
   endpoint timing/security semantics:
   https://developers.binance.com/en/docs/products/derivatives-trading-portfolio-margin-pro/general-info
2. Binance Developer Documentation — Futures trade/order API:
   https://developers.binance.com/en/docs/catalog/advanced-trading-derivatives-trading-portfolio-margin/api/rest-api/trade
3. Binance USDⓈ-M Futures change log:
   https://developers.binance.com/zh-CN/docs/products/derivatives-trading-coin-futures/change-log
4. Binance USDⓈ-M Futures WebSocket market-stream behavior:
   https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/websocket-market-streams/Connect
5. Binance Developer Documentation — official-interface policy:
   https://developers.binance.com/en/docs/introduction

Implementation boundary:
- The platform stores these references as external-reference evidence.
- The parity runner performs no production-order operation.
- Testnet mutation remains separately gated and fail-closed.
