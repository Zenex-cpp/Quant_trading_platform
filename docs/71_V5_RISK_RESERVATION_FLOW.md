# V5.0 §179 Risk Reservation Flow

This document defines the repository risk-reservation path for §68–§71, §152, and M20. It describes local code behavior and its fail-closed boundaries. It is not evidence that production accounting, trusted actor identity, or every service's SQLite wiring is deployed.

## Authorities and records

| Authority | Record or view | Responsibility |
| --- | --- | --- |
| Risk decision ledger | `RiskDecisionRecord` | Approves an exact intent, decision, exposure limit, truth hash, and reservation ID with a validity window. |
| Accounting authority | `AccountingProjection` and reconciled gate snapshot | Supplies the current projection hash and blocks new risk while accounting is unreconciled or unknown. |
| Reservation book | Append-only `RISK_*` events | Holds the budget allocation and reservation lifecycle; reconstructs the budget projection on restart. |
| Final dispatch guard | V3.11 dispatcher or V3.85 controlled Testnet submit | Rechecks the exact authorities, consumes a reservation before transport, and refuses missing or ephemeral ledgers. |
| Dispatch/side-effect ledgers | Attempt and submit records | Preserve the transport claim and outcome, including `UNKNOWN`, for restart and reconciliation. |

The reservation record binds `reservation_id`, scope, requested and allowed amounts, `intent_id`, `risk_decision_id`, `accounting_projection_hash`, creation time, and expiry. `allowed` cannot exceed `requested`; a dispatch amount cannot exceed `allowed`.

## Lifecycle

The allowed reservation lifecycle is:

```text
ABSENT -> RESERVED -> CONSUMED
                   -> RELEASED
                   -> EXPIRED
                   -> OVERRIDDEN
```

The four terminal states cannot transition again. Consumption, release, expiry, and override use an exclusive append for the reservation aggregate. Replaying the same reservation creation is idempotent only when the record payload matches exactly.

`schemas/v5_risk_reservation_flow.csv` is the machine-readable transition inventory. `RiskBudgetProjection` preserves `allocated`, `reserved`, `consumed`, `released`, `expired`, `overridden`, and `remaining`; released, expired, and overridden amounts are audit totals and are not credited a second time.

## Dispatch sequence

1. Build and reconcile accounting. The pre-trade snapshot and reservation bind the current accounting projection hash.
2. Record an allowed durable risk decision for the exact intent and reservation ID. Calculate the permitted reservation amount under the configured budget scope.
3. Call `DurableRiskReservationBook.reserve`. The book validates identity, amount, accounting hash, timestamps, and remaining budget. `EventStore.atomic()` acquires a SQLite `BEGIN IMMEDIATE` before replaying remaining budget and appending `RISK_RESERVED`, so concurrent connections cannot both allocate the same remaining funds.
4. Before an OPEN or INCREASE order reaches the gateway, the final guard requires persistent accounting and reservation ledgers, a reconciled accounting authority, a matching accounting projection hash, a valid risk decision, and the matching `RESERVED` record. V3.12 accepts the accounting authority and reservation gate through its constructor. V3.85 also requires a persistent dispatch store and a pre-trade snapshot with the current accounting projection hash.
5. The guard appends the exclusive `RISK_CONSUMED` event before the external submit. It then records and performs the one-shot dispatch using the durable attempt/side-effect ledgers.
6. An acknowledged, rejected, or ambiguous transport result is recorded. A transport exception leaves the reservation consumed and the order outcome unknown; restart or a gateway retry cannot consume it again or blindly resubmit it. The exchange reconciliation path resolves `UNKNOWN` before another risk-increasing dispatch.
7. On restart, the hash-chained event stream reconstructs reservation states and budget totals. A missing, corrupt, expired, terminal, conflicting, stale-accounting, or non-persistent authority blocks new risk.

## Release and recovery rules

- Release only a reservation for which durable evidence establishes that no order was sent. A reservation is not released just because the client timed out or the result is ambiguous.
- Expire only a reservation whose recorded expiry has passed. Expiry does not prove that an already submitted order was absent; dispatch state must also be reconciled.
- Override is an explicit terminal action and must include a reason. The book records the reason but does not authenticate the operator or independently validate override evidence; the trusted permission service must authorize the actor and evidence before calling it.
- If transport status is uncertain, keep the reservation consumed until reconciliation determines the venue outcome. Do not recreate a reservation with the same ID or retry the order to recover local state.
- Recovery never reconstructs a missing accounting projection from a reservation. A reservation with no current matching accounting hash is invalid under §70 and §152.

## Scope and known limits

The durable book accepts the prompt's SYSTEM, PORTFOLIO, STRATEGY, MODEL, TRADE, and ORDER scopes. This component enforces the allocation passed to that book; a platform-wide hard ceiling and correlated-exposure aggregation remain separate authorities. Risk reservations are consumed for OPEN and INCREASE dispatches; DECREASE and CLOSE are risk-reducing actions and use the position/closing-only controls instead.

The book requires persistent SQLite at dispatch, and reservation allocation and terminal transitions are serialized across SQLite connections. This does not prove production-wide store sharing, external accounting truth, authenticated reviewer/operator identity, venue behavior, or atomic deployment. Those remain explicit integration and evidence requirements.
