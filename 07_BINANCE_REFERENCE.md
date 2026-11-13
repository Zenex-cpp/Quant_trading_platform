# 07 — External Reference Register (implementation-time seed)

The MASTER PROMPT requires current official exchange documentation at implementation time. This V0.1 records only references used to define future adapter boundaries.

As of 2026-09-11, Binance documents Futures WebSocket market streams with a 24-hour maximum connection lifetime and ping/pong requirements; user-data streams expose ordered account/order events on a single connection and recommend WebSocket for continuously monitoring order/position state. These are adapter-level facts and MUST NOT leak into venue-agnostic core contracts.

Reference set:
- Binance WebSocket Market Streams — current documentation (last modified 2026-09-07): https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/websocket-market-streams/Connect
- Binance Futures user data streams — current documentation: https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/ws-api/user-data-streams

Implementation rule: capture retrieval timestamp, document version/hash where available, affected adapter component, and revalidation condition.


## V0.7 official reference update (2026-09-11)
Current Binance COIN-M futures documentation records: market WebSocket connections are valid for 24 hours; server ping is sent every 3 minutes and requires a pong within 10 minutes; the connection has a 10 incoming-message-per-second limit and up to 1024 subscribed streams. Binance recommends WebSocket user-data streams for order/position status during volatile periods. For the same user on a single user-data WebSocket connection, messages of the same event type are strictly ordered by transaction time and event time. The local order-book implementation therefore treats sequence continuity and recovery as hard contracts while keeping all venue-specific rules in the adapter.

## V0.8 USD-M historical archive import (reviewed 2026-11-11)

Primary implementation references, retrieved 2026-11-11:

- Binance Public Data README: https://github.com/binance/binance-public-data
- Binance Public Data helper usage and daily/monthly kline archive layout: https://github.com/binance/binance-public-data/blob/master/python/README.md
- Binance Vision dataset terms: https://github.com/binance/binance-public-data/blob/master/TERMS_AND_CONDITIONS.md

The official README documents USD-M Futures klines as the 12-column /fapi/v1/klines shape and says each ZIP has a sibling .CHECKSUM. Daily and monthly archives are published from data.binance.vision; data may arrive later or be corrected. The implementation reads only daily kline archive and checksum paths and records hashes for the raw archive and normalized data. It does not call the /fapi API.

The official dataset terms are version 1.0, last updated 2026-08-26. They state a CC BY-NC-SA 4.0, non-commercial license and exclude live proprietary/commercial trading, commercial order generation and paid signal distribution. Accordingly the downloader requires explicit non-commercial research attestation and its artifacts must not be fed into a live/commercial strategy. Recheck the source terms before future access; this reference register is not a legal determination.

Affected components: trading_platform.data.binance_public_data, trading_platform.v391.network_segmentation, and the trading-platform market-data CLI. Revalidate on source terms, archive schema, checksum format, URL layout or terms revision changes.
