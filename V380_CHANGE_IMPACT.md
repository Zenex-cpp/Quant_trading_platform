# V3.80 Change Impact

## Changed components

- `src/trading_platform/execution/models.py`: additive `OrderRequest.price` and `OrderRequest.time_in_force` fields.
- `src/trading_platform/v380/order_adapter.py`: new LIMIT-capable Testnet adapter/gateway boundary.
- `src/trading_platform/v380/user_data_reconciliation.py`: routed private WebSocket contract, user-data projection and reconciliation gate.

## Affected downstream components

- Testnet LIMIT order construction.
- User-data event normalization/projection.
- REST/WS account reconciliation.
- Execution evidence and compliance.

## Invalidation analysis

Historical V3.79 package artifacts remain immutable. The V3.80 implementation adds a
new adapter boundary instead of mutating the V3.79 execution adapter. Existing V3.79
MARKET behavior remains covered by the full regression suite.

## Required revalidation

Any Binance WebSocket routing change, OrderRequest schema change, order endpoint
semantic change, or user-data schema change requires rerunning V3.80 targeted tests,
full regression, evidence generation and the live connectivity probe.
