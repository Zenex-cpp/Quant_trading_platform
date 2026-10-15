# V3.4 Release Notes

V3.4 closes the execution-to-accounting loop without introducing network I/O into the core bridge.

## Added
- `trading_platform.v34.execution_bridge.ExecutionBridge`
- commit → exchange observation → fill → position → accounting linkage
- deterministic request ownership by `order_request_id`
- unknown exchange status → UNKNOWN → reconciliation-required path
- fill idempotency through the existing FillLedger
- position update through PositionLedger
- cost/P&L attribution through PnLLedger without inventing realized P&L
- explicit lifecycle observation for ack/fill/cancel/reject/expiry

## Safety
- No exchange/network call is performed by the bridge itself.
- A fill for a different order request is rejected.
- Unknown exchange status never triggers an implicit retry.
- Reconciliation evidence must resolve UNKNOWN before a new dispatch path is permitted.
