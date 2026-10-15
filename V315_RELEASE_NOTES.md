# V3.15 Release Notes

V3.15 extends V3.14 durable order-lifecycle recovery into durable economic state recovery.

Added:
- `trading_platform/v315/durable_accounting.py`
- append-only accounting events for fills, funding, and cash adjustments;
- deterministic position projection with signed quantity, average entry price, realized P&L, fees and funding;
- restart-safe reconstruction from the persistent event chain;
- event-id idempotency with conflicting reuse blocked;
- corruption detection through the existing hash-chained `EventStore`;
- explicit recovery proof and exchange reconciliation contract.

Safety posture:
- no credentials are persisted;
- no network I/O is introduced;
- corrupted accounting history fails closed;
- reconciliation does not grant trading permission by itself;
- `production_ready` remains `FALSE`.
