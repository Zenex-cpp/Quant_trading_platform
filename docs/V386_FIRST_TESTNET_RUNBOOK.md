# V3.86 First Authenticated Testnet Runbook

## Purpose
This runbook defines the first real USDⓈ-M BTCUSDT Testnet mutation. It is a controlled operational exercise, not live production trading.

## Hard prerequisites
Do not start the mutation path unless all of these are true:

- environment is TESTNET;
- `GET /fapi/v1/time` preflight is VERIFIED;
- local clock skew is within policy;
- the private user-data channel is healthy;
- the latest `ORDER_TRADE_UPDATE` / `ACCOUNT_UPDATE` observation is fresh;
- REST ↔ stream reconciliation is GREEN;
- the V3.84 activation is ACTIVE and unexpired;
- operator approval scope is `TESTNET_ORDER_MUTATION`;
- symbol is explicitly allowlisted (`BTCUSDT` in the current configuration);
- hard notional ceiling is satisfied;
- a valid immutable pre-trade snapshot exists;
- no unresolved UNKNOWN order/position/accounting/reconciliation state exists;
- the runtime credential source is available without persisting the secret.

## Credential boundary
Credentials must be supplied only at runtime. Never place an API secret in a repository, config file, evidence JSON, stdout log, event payload, manifest, or release artifact.

Recommended environment-variable names for the operator shell are:

- `BINANCE_TESTNET_API_KEY`
- `BINANCE_TESTNET_API_SECRET`
- `TESTNET_MUTATION_CONFIRM`

The confirmation value should be an explicit operator acknowledgement documented in the local run record. The secret value itself must never be echoed.

## Exact sequence

1. Run connectivity preflight.
2. Establish the private user-data session.
3. Verify event freshness.
4. Reconcile REST and stream state.
5. Obtain/verify operator approval.
6. Activate the V3.84 Testnet mutation authority.
7. Capture the V3.85 immutable pre-trade snapshot.
8. Prepare the durable dispatch attempt.
9. Submit exactly once through the V3.85 controlled boundary.
10. Observe the exchange result.
11. Consume `ORDER_TRADE_UPDATE` and `ACCOUNT_UPDATE`.
12. Reconcile REST ↔ stream ↔ position/accounting.
13. Close the operator session.

## Unknown outcomes
If the transport returns UNKNOWN, timeout, connection loss after submission, or any ambiguous response:

`STOP NEW RISK → QUERY/RECONCILE → RESOLVE ORDER STATE → RECONCILE POSITION/ACCOUNTING → ONLY THEN CONSIDER RESUME`

Never repeat the submission merely because an HTTP/WebSocket transport did not return an immediate success response.

## Expected first exercise
Use the smallest permitted notional within the configured V3.84 guard. The first exercise should prefer a deterministic, low-risk Testnet LIMIT order and should be closed/reconciled immediately after confirmation of the event chain.

## Evidence required
The run record must contain:

- connectivity evidence hash;
- operator approval ID;
- activation ID;
- pre-trade snapshot ID/hash;
- order request ID;
- client order ID;
- durable dispatch attempt ID;
- exchange order ID when available;
- `ORDER_TRADE_UPDATE` evidence;
- `ACCOUNT_UPDATE` evidence;
- reconciliation authorization ID;
- accounting result;
- incident ID if any step becomes UNKNOWN/DEGRADED;
- final recovery/reconciliation proof.

## References
Binance USDⓈ-M Futures documentation is the authoritative external reference at implementation/run time. Current documentation describes `ORDER_TRADE_UPDATE`, order status states, and time-in-force semantics; Binance's change log also documents the USDⓈ-M WebSocket base-URL migration and the `/private` path for user-data streams.
