# V4.29 M11 Durable Retry/Replay Boundary

**Status:** `TESTED`; exchange-side exactly-once behavior remains unverified.

## Finding

The final dispatcher silently constructed `DurableSideEffectLedger(EventStore())` when no V3.21 attempt ledger was configured. The default EventStore is in-memory, so the STARTED/SUCCEEDED evidence disappeared with the dispatcher/process. Recreating a dispatcher for the same committed request could submit it again. A local fake-gateway reproduction observed two submits.

## Change

- EventStore now exposes whether its database is file-backed.
- The dispatcher reuses the supplied persistent attempt ledger, order-request ledger, or accounting ledger store for its side-effect journal when possible.
- Before a new transport attempt, a non-persistent side-effect store fails closed with `SIDE_EFFECT_LEDGER_NOT_PERSISTENT`. An in-memory successful result may be replayed in the same process, but cannot authorize a new submit after that process-local record is absent.
- `ExecutionRuntimeIntegration` accepts and passes a durable dispatch-attempt ledger to the final dispatcher. Without persistent storage the runtime reports a blocked dispatch and does not call the gateway.
- The V4.29 compliance matrix, fixed preflight impact set, workflow validator and GitHub CI now include M11. The CI impact set also explicitly includes M10, which was already required by the fixed runner.

## Verification

Focused retry/replay, dispatcher, runtime, reconciliation and side-effect regressions passed **72 tests**. Coverage includes same-request dispatcher recreation with one gateway submit and a non-persistent ledger that fails before transport.

The mandatory Windows/Python 3.14.7 V4.29 runner on package `3.61.24` passed with **1,347 passed, 26 skipped**, `RELEASE_HYGIENE=PASS`. `.audit/V429_M11_DURABLE_RECHECK_20261112.json` recorded `READY_FOR_MILESTONE`, `allowed=true`, `pipeline_status=PASS`, zero blocking reasons, M10/M11/M18/M21/M25 in the impacted set, and 169 input hashes. `external_evidence=false`, `production_ready=false`, and `activation_flag=NOT_SET` remain unchanged.

The journal uses local SQLite persistence and synthetic gateways. This does not prove exchange-side idempotency, venue exactly-once semantics, or production deployment/reconciliation behavior. No exchange endpoint was contacted and no order was submitted.
