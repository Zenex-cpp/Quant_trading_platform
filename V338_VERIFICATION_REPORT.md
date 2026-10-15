# V3.38 Verification Report

Requirement: M11 — No duplicate side effect due to retry/replay.

Status: TESTED

Automated evidence:

- Durable side-effect result replays after a fresh process without a second execution.
- Crash window after `STARTED` blocks a second execution after restart.
- Transport uncertainty becomes `UNKNOWN` and blocks retry.
- Operation identity collisions fail closed.
- Secret material is excluded from persisted side-effect results.
- Tampered side-effect journal/hash chain fails closed.
- Dispatcher integration returns a durable completed result without a second gateway call.
- Risk reservation is not consumed twice on an idempotent retry.
- Focused M11 verification: 25 passed.
- Full regression: 482 passed.
- `compileall`: PASS.

Production readiness remains FALSE. The exact-once guarantee of a remote exchange remains outside the provable scope of the local journal and requires reconciliation of UNKNOWN external state.
