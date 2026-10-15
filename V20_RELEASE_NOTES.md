# V2.0 Release Notes

## Delivered
- REST↔WebSocket account/order reconciliation.
- Fail-closed reconciliation states: GREEN, RED, UNKNOWN/BLOCKED semantics through result state.
- Order status and executed quantity divergence detection.
- Position divergence detection.
- Stream stale/unhealthy blocking.
- Snapshot SHA-256 hashes for evidence.
- Recovery coordinator with resubscribe + forced reconciliation.
- Recovery VERIFIED/BLOCKED gate.

## Safety
No live credentials or exchange mutations were used during build verification. Production remains not ready until live Testnet evidence is obtained and the complete readiness chain passes.

## External references
- https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/ws-api/user-data-streams
- https://developers.binance.com/en/docs/products/derivatives-trading-coin-futures/user-data-streams
