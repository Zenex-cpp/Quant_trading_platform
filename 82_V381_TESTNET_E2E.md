# V3.81 Testnet End-to-End

## Scope

V3.81 closes the local end-to-end causal chain from `OrderIntent` through simulated exchange events, user-data projection, REST/WS reconciliation, fill accounting, position state and P&L/accounting.

The local harness is deterministic and no-network. It is intended to prove the software contract, not exchange behavior.

## Chain

`OrderIntent -> OrderRequest -> Exchange ACK (simulated) -> ORDER_TRADE_UPDATE -> ACCOUNT_UPDATE -> REST/WS reconciliation -> FillLedger -> PositionLedger -> Accounting/P&L`.

The harness exercises a partial-fill sequence followed by a final fill and then replays a duplicate trade event. Duplicate processing must not change cumulative quantity or the fill ledger.

## Negative path

A deliberate REST position mismatch produces `RED` reconciliation and blocks trading.

## Live boundary

The live runner performs a read-only `GET /fapi/v1/time` probe. It never submits a mutating order. A successful probe is environment evidence only; it does not establish authenticated order/fill/reconciliation parity.

A future operator-controlled Testnet mutation must require explicit approval, a hard notional cap, reconciliation GREEN, fresh risk decision, and a dedicated rollback/cancel plan.
