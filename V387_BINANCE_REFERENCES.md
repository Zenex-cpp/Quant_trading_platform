# V3.87 Binance References

Reference retrieval date: 2026-10-05.

1. Binance USDⓈ-M / derivatives change log: the 2026-03 WebSocket migration specifies `/private` for user-data paths; it also records the Testnet WebSocket base URL `wss://fstream.binancefuture.com` in the historical Testnet migration note. The current exact Testnet private path is therefore treated as an externally verified runtime reference, not hard-coded as an unproven fact.
2. Binance General Info: signed TRADE/USER_DATA operations require HMAC-SHA256 and millisecond `timestamp`; `recvWindow` is supported.
3. Binance USDⓈ-M user-data documentation: user-data events are ordered by `T` and `E`; the WebSocket connection is time-bounded and user-data should be preferred for order/position state over delayed REST queries when volatility is high.
4. Binance 2026 change log: `EXPIRED_IN_MATCH` is a recognized terminal order state in the current API family; the v3.87 observation layer treats it as terminal for reconciliation.

Source URLs are kept in the external evidence record and must be revalidated before production use.
