# V5.0 Recovery and Restart Plan

The unified restart runbook is `schemas/v5_recovery_restart_plan.csv`. It covers
process startup, market-stream gaps, unknown orders and retries, accounting
projection mismatch, risk-ledger replay, evidence/gate invalidation, and the
final recovery-proof/readiness step.

The order is mandatory. A lower-layer recovery cannot bypass an unresolved
higher-layer failure. Missing stores, invalid hash chains, unknown venue orders,
unreconciled accounting, stale risk authorities, active invalidations, or absent
recovery proof keep new risk and live readiness blocked. Each step names its
authoritative source, verification predicate, block condition, and owner.

This is a repository runbook. It does not prove operator coverage, venue access,
or a production exercise.
