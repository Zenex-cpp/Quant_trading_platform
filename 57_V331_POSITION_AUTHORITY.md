# V3.31 — Durable Position Authority

## Purpose
V3.31 closes the machine-enforcement gap behind M3:

> No Order when Position = UNKNOWN.

The platform now separates reconciliation evidence from execution authority. REST/WS reconciliation remains the evidence producer. `PositionAuthorityLedger` persists the resulting position authorization and becomes the final order-usable position authority on the runtime dispatch path.

## Contract
A position authorization is `VERIFIED` only when the supplied reconciliation result is `GREEN` and its diff is clean. Otherwise the authority becomes `UNKNOWN` and order submission is blocked.

Every authorization is:
- append-only and hash-chained through `EventStore`;
- symbol-bound;
- fingerprinted;
- time-bounded with `valid_from_ms` and `expires_at_ms`;
- replayable after restart.

Missing, expired, corrupt or unknown position authority fails closed before transport.

## Runtime integration
`ExecutionRuntimeIntegration` now owns/injects `PositionAuthorityLedger`. `GuardedExecutionDispatcher` consults the authority immediately before the external transport boundary. The runtime simulation clock is propagated into the dispatcher so position TTL evaluation is deterministic and consistent with the orchestration cycle.

## Scope
This release does not claim live venue reconciliation evidence or independent review. M3 moves from `PARTIAL` to `TESTED`; `VERIFIED` remains gated by the Master Prompt evidence/review definition.
