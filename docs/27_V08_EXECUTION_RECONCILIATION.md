# V0.8 — Execution / Reconciliation / Testnet

## Scope

Execution state machine, OrderRequest adapter boundary, unknown-order procedure, partial-fill accounting inputs, venue rule normalization, reconciliation triggers and recovery proof.

## Safety

The included adapter is TESTNET-only by construction. It rejects configurations whose environment is not `TESTNET`. No credentials are stored in source/config and no network transport implementation is bundled.

## Order lifecycle

`CREATED → SUBMITTED → ACKNOWLEDGED → PARTIALLY_FILLED → FILLED`

Cancellation and rejection are explicit terminal paths. `UNKNOWN` is non-terminal and requires `QUERY → RECONCILE → DECIDE`. Blind retries are blocked.

## Venue rules

Precision uses explicit tick/step sizes and minimum quantity/notional. Precision fields are not treated as substitutes for actual venue filters.

## Reconciliation

Triggers: startup, pre-trade, post-trade, post-restart, event-driven and scheduled. Recovery is verified only when state is reconciled, invariants pass, no unresolved critical issue exists and guards pass.

## Binance references

Current Binance developer documentation records `ORDER_TRADE_UPDATE` order-state/execution events and `ACCOUNT_UPDATE` position/balance events. It also states that user-data stream messages for the same event type on a single connection are strictly ordered by transaction/event time, and recommends prioritizing WebSocket user data for account/order state under volatile conditions. See the project Binance reference document for captured reference metadata.
