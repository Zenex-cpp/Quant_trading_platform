# V3.87 First Testnet Order Runbook

## Objective

Execute exactly one controlled Testnet order only when every higher-priority safety gate is satisfied.

## Required sequence

1. Run V3.83 connectivity preflight.
2. Establish authenticated user-data stream health and prove fresh events.
3. Reconcile REST/WS state and require `GREEN`.
4. Obtain operator approval scoped to `TESTNET_ORDER_MUTATION`.
5. Activate V3.84 mutation authority.
6. Capture immutable V3.85 pre-trade snapshot.
7. Obtain a fresh `BTCUSDT` bid/ask snapshot.
8. Construct a `LIMIT + GTC` order that is demonstrably non-marketable by at least the configured minimum distance.
9. Require `FirstTestnetOrderRunnerV387.prepare()` to return `ARMED`.
10. Submit exactly once through V3.86/V3.85.
11. Observe the matching user-data event correlated by `client_order_id`.
12. Require monotonic event time (`E`, with `T` preserved where available).
13. Reconcile order, position and accounting.
14. Close the operator session and invalidate activation.

## Hard blocks

`NOT_VERIFIED`, stale quote, missing user-data health, reconciliation mismatch, unknown position, non-marketable proof failure, notional ceiling breach, duplicate dispatch intent, timeout/UNKNOWN, or closed session.

## Default mutation stance

No real mutation is attempted by the release verification runner. The current runtime's public Testnet DNS preflight remains independent evidence and may remain `NOT_VERIFIED`.

## Safety invariant

The first Testnet order is not allowed merely because it is small. It must also be proven non-marketable against a fresh quote, so an accidental immediate execution is not treated as an acceptable test side effect.
