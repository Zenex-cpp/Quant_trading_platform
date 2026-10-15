# V3.22 — Durable Dispatch Reconciliation

V3.21 made the pre-transport attempt durable and deliberately non-retryable while PENDING or UNKNOWN. V3.22 adds the missing closure path: independently obtained reconciliation evidence can resolve the existing attempt without authorizing a second submission.

## Contract

`PENDING/UNKNOWN attempt -> independent evidence -> durable reconciliation -> recovery-visible closure`

Supported evidence sources are explicitly bounded to `USER_STREAM`, `REST_ORDER_STATUS`, and `SUBMIT_RESPONSE`.

Persisted reconciliation authority contains only:
- order_request_id;
- intent_id;
- immutable attempt_id;
- client_order_id;
- resolved dispatch state;
- exchange_order_id when known;
- evidence_id;
- evidence source;
- evidence fingerprint;
- evidence observation timestamp.

Raw payloads, credentials, sockets and transport objects are never persisted.

## Safety invariants

- PENDING/UNKNOWN remains non-retryable.
- Reconciliation cannot create a new dispatch attempt.
- Evidence must resolve to a terminal dispatch state.
- Evidence must belong to the exact durable attempt.
- Evidence timestamp cannot precede the attempt or a prior durable observation.
- Conflicting evidence reuse fails closed.
- Corrupt EventStore chain fails closed.
- Recovery is incomplete while an attempt remains PENDING/UNKNOWN without a durable reconciliation closure.

## Recovery

`assert_recovery_closed()` is an explicit machine check. It does not activate trading by itself; existing permission, accounting, risk, intent, request, attempt and exchange-boundary gates remain mandatory.

## Execution integration

The Binance user-execution correlation path may be configured with the V3.21 attempt ledger and this V3.22 reconciliation ledger. A correlated terminal user-stream order update closes an existing PENDING/UNKNOWN attempt using the event hash as evidence identity. REST unknown-order reconciliation closes the same durable case from bounded `REST_ORDER_STATUS` evidence.

The durable closure is written before the in-memory bridge lifecycle is advanced, so a failed evidence commit cannot leave a partially advanced execution state.

## Recovery gate integration

`UserStreamSessionCoordinator` may receive the reconciliation ledger. In that mode an otherwise positive recovery assessment cannot transition the session to `ACTIVE` while any durable dispatch attempt remains PENDING/UNKNOWN without a closure record.
