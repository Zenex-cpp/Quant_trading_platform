# V3.39 Release Notes

M12 — No double-counted fill.

The fill boundary now enforces a canonical venue fill identity. Binance trade updates carry the exchange order ID + trade ID into the normalized `Fill`; `FillLedger` accepts each economic fill once, and incompatible reuse of the same identity fails closed. `ExecutionBridge` no longer mutates position/P&L projections on duplicate fills.

`DurableFillAuthority` persists accepted fill identities in the append-only EventStore so a restart or a second evidence source cannot re-book the same venue trade under a different local fill ID.

`DurableAccountingLedger` uses the same identity rule for persistent fill events, preserving the existing local `fill_id` behavior for legacy records without venue trade IDs.
