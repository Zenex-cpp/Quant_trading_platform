# V3.21 — Durable Dispatch Attempts

V3.20 made the exact committed `AuthorizedOrderRequest` durable. V3.21 closes the transport crash window by making the dispatch attempt itself durable before external I/O.

## Contract

For a configured V3.21 ledger the final dispatcher executes:

`exact durable OrderRequest -> durable PENDING attempt -> external transport -> durable outcome -> bridge lifecycle`

The `PENDING` record is the non-retry marker. If the process dies after transport but before acknowledgement, restart/re-entry sees the durable attempt and blocks a second submission. A `UNKNOWN` outcome also blocks reuse until reconciliation.

The attempt binds:
- `intent_id`
- `order_request_id`
- `client_order_id`
- exact V3.20 request fingerprint
- exact OrderIntent fingerprint
- idempotency key
- immutable attempt id

A resolved observation records only execution evidence: state, exchange order id when known, exchange outcome and reason. Credentials, secrets, sockets and transport objects are excluded.

## Failure semantics

- no previous attempt -> prepare PENDING then transport;
- PENDING -> reconciliation required, no second transport;
- UNKNOWN -> reconciliation required, no second transport;
- ACKNOWLEDGED/REJECTED/CANCELLED -> same OrderRequest cannot be submitted again;
- hash-chain corruption -> replay fails closed;
- payload/binding conflict -> dispatch denied.

Persistence does not authorize trading. Existing permission, recovery, accounting, risk-decision, reservation, OrderIntent, OrderRequest, lifecycle and exchange-boundary gates remain mandatory.
