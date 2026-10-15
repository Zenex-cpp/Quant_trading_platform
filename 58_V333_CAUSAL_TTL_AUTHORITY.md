# V3.33 — Causal TTL Authority

V3.33 closes the cross-domain TTL gap identified by Master Prompt sections 20–22 and machine checks M5/M30.

## Contract

The durable causal chain is:

`PREDICTION → SIGNAL → OPPORTUNITY → PORTFOLIO_DECISION → RISK_DECISION → ORDER_INTENT`

Every downstream artifact must:
- reference an existing upstream artifact;
- reference the required upstream artifact type;
- be recorded while upstream evidence is valid;
- never outlive its upstream expiry;
- carry a valid state and immutable fingerprint.

## Final runtime enforcement

`ExecutionRuntimeIntegration` always provisions `CausalTTLAuthorityLedger`.

For `OPEN` / `INCREASE`, the final runtime dispatch path rejects:
- missing causal chain;
- expired upstream artifact;
- invalid/suspended upstream artifact;
- downstream artifact whose TTL outlives its upstream dependency;
- root intent window mismatch;
- corrupted EventStore chain.

The lower-level `GuardedExecutionDispatcher` accepts the authority as an explicit dependency. Production-oriented runtime integration always supplies it; isolated primitive tests may intentionally omit it.

## Recovery / replay

The ledger is append-only, hash-chained and restart-reconstructible. Duplicate artifact IDs are idempotent only when the payload is identical. Conflicting reuse fails closed.
