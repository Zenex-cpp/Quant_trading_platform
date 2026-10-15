# V3.11 — Runtime trading permission as an effective dispatch guard

V3.11 closes the last control-plane gap from V3.10: `trading_allowed` is now enforced at the final external submit boundary.

## Contract

`Capability -> CommitCoordinator -> ExecutionBridge -> DispatchGuard -> Exchange Gateway`

Before a risk-increasing submit reaches transport, the dispatcher requires:

1. a currently committed `OrderRequest` for the intent;
2. `RuntimeCycleSnapshot.trading_allowed == True`;
3. `recovery_required == False`;
4. the local bridge lifecycle is dispatchable and not `UNKNOWN`.

A denied guard raises `DispatchGuardDenied` and makes **zero** gateway calls.

An unresolved local `UNKNOWN` raises the existing reconciliation error and makes **zero** gateway calls.

The dispatcher sends the exact committed `OrderRequest`; it does not rebuild, mutate, or enlarge the order at the final boundary.

## Scope

This guard covers risk-increasing external order submission. Cancel / close-only behavior is not inferred from `trading_allowed`; such actions require an explicit close-only authorization path.

## TOCTOU boundary

The V3.10 runtime is single-thread-friendly and exposes deterministic snapshots. V3.11 evaluates the authoritative snapshot immediately before the transport invocation. Concurrent scheduling should continue to use the same runtime serialization boundary rather than bypassing the dispatcher.

## Safety result

`trading_allowed = false` ⇒ no new external submit.

`recovery_required = true` ⇒ no new external submit.

`UNKNOWN` local execution state ⇒ no blind retry.
