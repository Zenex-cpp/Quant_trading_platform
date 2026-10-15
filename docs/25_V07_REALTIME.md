# V0.7 — Realtime / Order Book / Microstructure Foundation

V0.7 implements realtime contracts without enabling live trading.

## Venue boundary
The core remains venue-agnostic. Binance-specific semantics belong to the adapter. Current official Binance futures documentation used for this milestone records 24-hour market WebSocket connection limits, ping/pong requirements, a 10 incoming-message-per-second connection limit, up to 1024 streams per connection, and recommends WebSocket user-data streams for order/position status under volatile conditions. User-data stream messages of the same event type on one connection are ordered by transaction/event time. These facts are external references, not core invariants.

## Order book contract
A local book is valid only after a snapshot is loaded and incremental updates advance contiguously. Duplicate/old updates have no side effects. A sequence gap, crossed book, invalid level, or missing snapshot transitions to recovery-required behavior and blocks use as a synchronized microstructure source.

## Microstructure
Derived fields include best bid/ask, mid, spread, spread in bps, depth and top-N imbalance. These are descriptive features only; no trading signal is introduced here.

## Clock contract
Source/event time, local wall-clock and monotonic timing are distinct. Excessive NTP/PTP offset yields INVALID clock integrity and must block new entry upstream according to the Master Prompt.

## Rate limiting
Rate-limit budget is modeled as a hard resource. Exceeding remaining budget is a machine-checkable failure, not a soft warning.

## Safety posture
Research, replay and simulation only. No credentials, live order submission, autonomous deployment, or production endpoints are implemented.
