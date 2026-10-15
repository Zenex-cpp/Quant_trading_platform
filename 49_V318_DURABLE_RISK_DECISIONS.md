# V3.18 — Durable Risk Decisions & Final TTL Gate

V3.18 closes the durable `RiskDecision` gap and makes final freshness checks coherent.

## Contract

A `RiskDecisionRecord` persists:
- decision identity and action (`ALLOW|REDUCE|REJECT|EXIT|EMERGENCY_HALT`);
- risk system state (`NORMAL|ELEVATED|RESTRICTED|FROZEN|EMERGENCY|RECOVERY`);
- requested/allowed exposure;
- active limits and multipliers;
- reservation and intent binding;
- valid-from / expiry TTL;
- configuration, risk-state, portfolio and position versions;
- provenance, truth hash and input fingerprint.

The ledger is append-only and hash-chained through `EventStore`, replayed deterministically after restart, and idempotent on immutable decision identity.

## Final pre-transport freshness

`GuardedExecutionDispatcher` captures exactly one clock sample and uses it to validate:
1. runtime permission/recovery state;
2. `OrderIntent` TTL/window;
3. `OrderRequest.deadline`;
4. durable `RiskDecision` TTL and bindings;
5. accounting gate;
6. durable risk reservation consumption.

No external transport occurs if a preceding freshness/identity check fails.

## Safety

`RiskDecisionGate` fails closed for expired/future decisions, non-ALLOW actions, frozen/emergency/recovery states, intent/reservation mismatch, exposure above allowed, stale truth hash, or stale explicitly supplied version bindings.

No credentials or autonomous network I/O are introduced. `production_ready = FALSE` remains unchanged.
