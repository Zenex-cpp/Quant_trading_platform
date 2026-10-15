# V3.85 Release Notes — Controlled Testnet Submit Boundary

## Scope
V3.85 implements the first durable, fail-closed mutation path after V3.84 activation.

Pipeline:

`Activation -> PreTradeSnapshot -> OrderRequest -> DurableDispatchAttempt(PENDING) -> ExternalSubmit -> Observation`

If transport fails after the dispatch attempt is durably recorded, state becomes `UNKNOWN` and blind retry is blocked until reconciliation.

## Implemented
- Immutable pre-trade snapshot with hashed state domains:
  positions, portfolio, risk, limits, market, liquidity, model health,
  strategy health, versions and causal decision chain.
- Hard pre-trade gates for:
  `POSITION != UNKNOWN`, `ACCOUNTING=RECONCILED`, `RECONCILIATION=GREEN`, `market_stale=false`.
- Snapshot-to-intent and snapshot-to-order-request binding.
- Durable dispatch attempt claim before external transport using the existing V3.21 append-only ledger.
- One-side-effect rule for the same `OrderRequest`/idempotency binding.
- Transport exception -> `UNKNOWN` + no blind retry.
- Credentials are passed only to the transport call and are never persisted in the V3.85 state/evidence ledger.
- Evidence runner distinguishes local verification from real Testnet connectivity.

## Not claimed
- Real Binance Testnet mutation was not executed.
- Real DNS/HTTP/WebSocket connectivity remains `NOT_VERIFIED` in the current runtime.
- Production readiness remains `FALSE`.
