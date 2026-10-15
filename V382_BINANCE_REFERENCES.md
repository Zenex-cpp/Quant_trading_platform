# V3.82 Binance References

The implementation is aligned to the current Binance documentation reviewed for this release:

1. USDⓈ-M Futures User Data Streams / WebSocket API user-data methods: `userDataStream.start`, `userDataStream.ping`, `userDataStream.stop`.
   https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/ws-api/user-data-streams

2. Futures User Data Streams lifecycle, `listenKeyExpired`, ordering and connection-lifetime guidance.
   https://developers.binance.com/en/docs/products/derivatives-trading-coin-futures/user-data-streams

The exact Testnet WebSocket API URL is intentionally configuration-driven in V3.82 because the reviewed public documentation does not establish a current Testnet-specific `ws-fapi` hostname strongly enough for a hardcoded production claim. Absent explicit operator configuration, live authenticated connectivity remains NOT_VERIFIED.
