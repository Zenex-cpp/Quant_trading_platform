# Trading Platform v3.84 — Binance Reference Basis

External references reviewed for the release:

1. Binance USDⓈ-M Futures WebSocket API — User Data Streams:
   https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/ws-api/user-data-streams
   - `userDataStream.start`
   - `userDataStream.ping`
   - `userDataStream.stop`
   - API key requirement
   - 60 minute stream lifetime / keepalive behavior

2. Binance USDⓈ-M Futures REST / general endpoint security:
   https://developers.binance.com/en/docs/products/derivatives-trading-portfolio-margin-pro/general-info
   - signed endpoint timing uses Unix timestamp in milliseconds;
   - `recvWindow` timing constraint;
   - API-key based endpoint access.

3. Binance derivatives change log:
   https://developers.binance.com/zh-CN/docs/products/derivatives-trading-coin-futures/change-log
   - 2026 WebSocket base-URL migration context;
   - `/private` path for USDⓈ-M user-data streams.

These are external reference inputs. They are not themselves evidence that this runtime can reach Binance Testnet.
