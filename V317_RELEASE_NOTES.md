# V3.17 Release Notes

V3.17 closes the durable risk-budget gap after V3.16.

Added:
- `trading_platform/v317/durable_risk.py`;
- durable, hash-chained risk reservation ledger;
- deterministic replay and restart recovery;
- idempotent reservation creation and terminal transition identity;
- binding of each risk reservation to intent, risk decision and accounting projection hash;
- fail-closed pre-transport reservation gate;
- `OrderIntent.risk_reservation_id` as the explicit linkage from intent to durable reservation;
- deterministic injected clock for gate timestamps in tests.

Correctness:
- duplicate reservation reuse with the same immutable payload is idempotent;
- conflicting reservation reuse is rejected;
- double consumption is rejected;
- stale accounting bindings are rejected;
- expired reservations cannot be consumed;
- released/expired/overridden amounts are not double-credited to `remaining`.

Safety posture:
- consumption is persisted before external transport;
- transport ambiguity therefore cannot create a second risk commitment automatically;
- no credentials or autonomous network I/O added;
- `production_ready = FALSE` remains unchanged.
