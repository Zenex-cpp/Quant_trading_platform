# Trading Platform v3.84 — Change Impact

Changed component: Testnet mutation boundary.

Upstream dependencies:
- v3.83 Testnet connectivity preflight evidence;
- v3.80 complete OrderRequest/venue adapter;
- existing reconciliation state model;
- network policy.

Downstream components:
- future Testnet submit/cancel/query paths.

Safety impact:
- no mutation may be authorized solely by configuration flags;
- connectivity evidence must be current and hash-bound;
- operator approval is mandatory;
- reconciliation must be GREEN;
- activation expires automatically;
- kill switch forces new-risk block.

No historical v3.73-v3.83 code is modified in place. v3.84 is additive and creates a new authority/adapter boundary.

Invalidation/revalidation:
- expired connectivity proof -> re-preflight;
- expired operator approval -> new approval;
- reconciliation RED -> halt/deactivate and reconcile;
- changed endpoint/configuration -> new activation;
- changed hard notional or symbol policy -> new activation and evidence.
