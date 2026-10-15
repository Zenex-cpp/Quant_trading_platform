# V2.0 — REST↔WebSocket Reconciliation & Recovery

V2.0 closes the state-integrity loop between authenticated user-stream state and authoritative REST snapshots.

Safety rule: trading is allowed only when reconciliation is GREEN and the user stream is healthy and non-stale. Any divergence, expiry, unknown event, stale stream, or failed recovery is fail-closed.

The reconciler compares open orders by `orderId`/`clientOrderId`, order status, executed quantity, and position amounts by symbol. It emits hashes of the REST and stream snapshots for evidence and produces a machine-readable GREEN/RED/BLOCKED result.

Recovery re-subscribes when possible, forces a REST↔WebSocket reconciliation, and enters VERIFIED only on a clean match. Otherwise it remains BLOCKED.

Binance's current documentation recommends WebSocket user-data messages for continuous order/position monitoring and describes `listenKeyExpired` and user stream keepalive behavior. REST remains the reconciliation source, not a substitute for the stream. See official references recorded in the release notes.
